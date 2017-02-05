#!/usr/bin/env python3
#
# Distributed under terms of the MIT license.
#
# Copyright (c) 2017 Olaf Lessenich
#

import argparse
import email
import nntplib
import time
import pymysql
import traceback


status = '0 %'
attempts = 2  # number of attempts in case of temporary error
aggressive = False

db = pymysql.connect(host="localhost",
                     user="lists",
                     passwd="lists",
                     db="mailinglists",
                     autocommit=True)
cur = db.cursor()


def log(target, action, number, msgno, msgid):
    print('%5s | %-4s | %-5s | %d(%s): %s' % (status, target, action, number,
                                              msgno, msgid))


def list_groups():
    nntpconn = nntplib.NNTP('news.gmane.org')
    resp, lists = nntpconn.list()

    for group, last, first, flag in lists:
        print(group)

    nntpconn.quit()


def contains(listid, msgid):
    if cur.execute('SELECT b.id FROM mboxes b, mails m WHERE b.id=%s and m.id=b.id and m.message_id=%s',
                   (listid, msgid,)) > 0:
        return cur.fetchone()[0]
    else:
        return None


def stat(nntpconn, msgno):
    for attempt in range(attempts):
        try:
            resp, number, msgid = nntpconn.stat(str(msgno))
        except nntplib.NNTPTemporaryError:
            print('%d: Temporary error. Sleep 5 seconds and retry.' % msgno)
            if not aggressive:
                time.sleep(5)
            pass
        else:
            break
    else:
        print('%d: Failed to stat after %d attempts' % (msgno, attempts))
        raise Exception('%d: Failed to stat after %d attempts'
                        % (msgno, attempts))

    log('nntp', 'STAT', number, msgno, msgid)
    return number, msgid


def get(nntpconn, msgno):
    for attempt in range(attempts):
        try:
            resp, info = nntpconn.article(str(msgno))
        except nntplib.NNTPTemporaryError:
            print('%d: Temporary error. Sleep 5 seconds and retry.' % msgno)
            if not aggressive:
                time.sleep(5)
            pass
        else:
            break
    else:
        print('%d: Failed to download after %d attempts' % (msgno, attempts))
        raise Exception('%d: Failed to download after %d attempts'
                        % (msgno, attempts))

    text = str()
    for line in info.lines:
        text += (line.decode('ascii', 'ignore')) + "\n"

    log('nntp', 'GET', info.number, msgno, info.message_id)
    return(info.number, info.message_id, email.message_from_string(text))


def check(listid, nntpconn, msgno, update):

    if update:
        number, msgid = stat(nntpconn, msgno)
    else:
        number = msgno
        msgid = 'unknown msg-id'

    if not update or not contains(listid, msgid):
        queue = True
        action = 'QUEUE'
    else:
        queue = False
        action = 'SKIP'

    log('db', action, number, msgno, msgid)
    return queue


def lookup_person(name, address):
    if cur.execute('SELECT `id` from `persons` where `name` = %s and `address` = %s', (name, address)) > 0:
        personid = int(cur.fetchone()[0])
    else:
        cur.execute('INSERT INTO `persons` (`name`, `address`) VALUES (%s,%s)',
                    (name, address))
        personid = int(cur.lastrowid)

    return personid


def lookup_type(name):
    if cur.execute('SELECT id from recipient_types where name = %s',
                   (name)) > 0:
        typeid = cur.fetchone()[0]
    else:
        cur.execute('INSERT INTO recipient_types (`name`) VALUES (%s)',
                    (name,))
        typeid = cur.lastrowid

    return typeid


def store(listid, nntpconn, msgno):
    number, msgid, msg = get(nntpconn, msgno)
    msgid = msg.get('Message-Id')
    date = msg.get('Date')
    subject = msg.get('Subject')
    lines = msg.get('Lines')

    sender = email.utils.parseaddr(msg.get('From'))
    senderid = lookup_person(*sender)

    cur.execute('INSERT INTO `mails` (`message_id`, `subject`, `date`, `from`, `lines`, `content`) VALUES (%s,%s,%s,%s,%s,%s)',
                (msgid, subject, date, senderid, lines, msg.as_string()))
    mailid = cur.lastrowid

    # these contain lists  of realname, addr tuples
    tos = msg.get_all('to', [])
    ccs = msg.get_all('cc', [])

    totypeid = lookup_type('to')
    cctypeid = lookup_type('cc')

    for to in email.utils.getaddresses(tos):
        toid = lookup_person(*to)
        cur.execute('INSERT INTO `recipients` (`mail`, `recipient`, `type`) VALUES (%s,%s,%s)',
                   (mailid, toid, totypeid))

    for cc in email.utils.getaddresses(ccs):
        ccid = lookup_person(*cc)
        cur.execute('INSERT INTO `recipients` (`mail`, `recipient`, `type`) VALUES (%s,%s,%s)',
                   (mailid, ccid, cctypeid))

    cur.execute('INSERT INTO `mboxes` (`list`, `mail`) VALUES (%s, %s)',
               (listid, mailid))

    action = 'STORE'

    log('mbox', action, number, msgno, msgid)


def initialize_list(group):
    cur.execute("SELECT `id` FROM `lists` WHERE `name` = %s", (group,))
    listid = cur.fetchone()

    if not listid:
        cur.execute("INSERT INTO `lists` (`name`) VALUES (%s)", (group,))
        listid = cur.lastrowid

    return listid


def download(group, dry_run, number=None, start=None, update=None):
    """
    The default behavior is to pause 30 seconds every 1000 messages while
    downloading to reduce the load on the load on the gmane servers.
    This can be skipped by setting the global aggressive flag.

    If the update argument is supplied, only new messages (i.e., msgid not in
    mbox) will be added to the mbox.
    """

    global status

    if not dry_run:
        listid = initialize_list(group)

    nntpconn = nntplib.NNTP('news.gmane.org')

    resp, count, first, last, name = nntpconn.group(group)
    print(
        'Group %s has %d articles, range %d to %d' %
        (name, count, first, last))

    last = int(last)

    if start:
        startnr = max(first, start)
        startnr = min(startnr, last)

        if number:
            last = min(startnr + number, last)

    else:
        startnr = first

        if number:
            startnr = max(startnr, last - number)

    if not start:
        print('No start message provided, starting at %d' % startnr)

    print("Checking messages %d to %d." % (startnr, last))

    stack = []

    # Check which messages need to be retrieved
    for msgno in reversed(range(startnr, last + 1)):
        try:
            if not aggressive and (msgno % 1000 == 0) and (msgno != startnr):
                print('%d: Sleep 30 seconds' % msgno)
                time.sleep(30)

            if dry_run:
                print('Dry-run: download message no. %d' % msgno)
                continue

            status = str(int(100 * (last - msgno) / (last - startnr))) + ' %'

            if check(listid, nntpconn, msgno, update):
                stack.append(msgno)
            else:
                print('Found a message that is already in the mbox.')
                break

        except:
            traceback.print_exc()
            pass

    # actually retrieve the messages
    length = len(stack)
    count = 0

    print("Retrieving %d messages." % length)

    while stack:
        count += 1
        status = str(int(100 * count / length)) + ' %'
        msgno = stack.pop()

        store(listid, nntpconn, msgno)

    nntpconn.quit()


def main():
    global aggressive
    parser = argparse.ArgumentParser()
    parser.add_argument("-a",
                        "--aggressive",
                        help="Disable waiting during a download",
                        action="store_true")
    parser.add_argument("-d",
                        "--dry-run",
                        help="perform a trial run with no changes made",
                        action="store_true")
    parser.add_argument("-n",
                        "--number",
                        help="Fetch the n most recent messages",
                        type=int)
    parser.add_argument("-l",
                        "--list-groups",
                        help="list all available groups and exit",
                        action="store_true")
    parser.add_argument("-s",
                        "--start",
                        help="First message in range",
                        type=int)
    parser.add_argument("-u",
                        "--update",
                        help="retrieve only new messages",
                        action="store_true")
    parser.add_argument("groups", default="[]", nargs="*")
    args = parser.parse_args()

    if args.list_groups:
        list_groups()
        return

    aggressive = args.aggressive

    for group in args.groups:
        try:
            download(group,
                     args.dry_run,
                     args.number,
                     args.start,
                     args.update)
        except:
            traceback.print_exc()
            pass


if __name__ == "__main__":
    main()
