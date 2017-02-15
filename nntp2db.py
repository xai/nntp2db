#!/usr/bin/env python3
#
# Distributed under terms of the MIT license.
#
# Copyright (c) 2017 Olaf Lessenich
#

import argparse
import email
import email.policy
import nntplib
import time
import pymysql
import traceback
import pytz
import json


status = '0 %'
attempts = 2  # number of attempts in case of temporary error
aggressive = False
keep_going = False
config = json.load(open('config.json'))

db = pymysql.connect(host=config['host'],
                     user=config['user'],
                     passwd=config['passwd'],
                     db=config['db'],
                     charset=config['charset'],
                     autocommit=config['autocommit'])
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
    sql = ('SELECT b.id FROM `mbox` b, `mail` m, `list` l '
           'WHERE l.id=%s '
           'and b.list=l.id '
           'and b.mail=m.id '
           'and m.message_id=%s '
           'LIMIT 1')
    if cur.execute(sql, (listid, msgid,)) > 0:
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
    return(info.number, info.message_id,
           email.message_from_string(text, policy=email.policy.default))


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
    sql = ('SELECT `id` from `person` '
           'where `name` = %s '
           'and `address` = %s '
           'LIMIT 1')
    if cur.execute(sql, (name, address)) > 0:
        personid = cur.fetchone()[0]
    else:
        sql = ('INSERT INTO `person` '
               '(`name`, `address`) '
               'VALUES (%s, %s)')
        cur.execute(sql, (name, address))
        personid = cur.lastrowid

    return personid


def slice_mail(msg):
    # parse mail
    header = list()
    body = list()
    isbody = False

    for line in msg.as_string().splitlines():
        if isbody:
            body.append(line)
            continue
        elif line.strip() == '':
            isbody = True

        header.append(line)

    return header, body


def parse_date(msg):
    dt = msg.get('Date').datetime

    if not dt.tzinfo:
        dt = dt.replace(tzinfo=pytz.utc)

    utc_date = dt.astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')
    utc_offset = dt.strftime('%z')
    return utc_date, utc_offset


def lookup_mail(msgid):
    sql = ('SELECT `id` from `mail` '
           'WHERE `message_id`=%s')

    if cur.execute(sql, (msgid,)) > 0:
        return cur.fetchone()[0]
    else:
        return None


def store(listid, nntpconn, msgno):
    try:
        number, msgid, msg = get(nntpconn, msgno)
    except:
        return
    msgid = msg.get('Message-Id')

    if contains(listid, msgid):
        return

    subject = msg.get('Subject')[:1023]
    lines = msg.get('Lines')

    mailid = lookup_mail(msgid)

    if not mailid:
        header, body = slice_mail(msg)

        sender = email.utils.parseaddr(msg.get('From'))
        senderid = lookup_person(*sender)

        utc_date, tz = parse_date(msg)

        sql = ('INSERT INTO `mail` '
               '(`message_id`, `subject`, `date`, `timezone`, `from`, '
               '`lines`, `header`, `content`) '
               'VALUES (%s, %s, %s, %s, %s, %s, %s, %s)')
        cur.execute(sql, (msgid, subject, utc_date,
                          tz, senderid, lines,
                          '\n'.join(header), '\n'.join(body)))
        mailid = cur.lastrowid

        # these contain lists  of realname, addr tuples
        tos = msg.get_all('to', [])
        ccs = msg.get_all('cc', [])

        for to in email.utils.getaddresses(tos):
            toid = lookup_person(*to)
            sql = ('INSERT INTO `recipient` '
                   '(`mail`, `recipient`, `to`, `cc`) '
                   'VALUES (%s, %s, %s, %s)')
            cur.execute(sql, (mailid, toid, 1, 0))

        for cc in email.utils.getaddresses(ccs):
            ccid = lookup_person(*cc)
            sql = ('INSERT INTO `recipient` '
                   '(`mail`, `recipient`, `to`, `cc`) '
                   'VALUES (%s, %s, %s, %s)')
            cur.execute(sql, (mailid, ccid, 0, 1))

        # references and in-reply-to
        in_reply_to = msg.get('in-reply-to')
        references = msg.get('references')

        if in_reply_to:
            for replyto in in_reply_to.replace('><', '> <').split():
                sql = ('INSERT INTO `in_reply_to` '
                       '(`mail`, `replyto_message_id`) '
                       'VALUES (%s, %s)')
                try:
                    cur.execute(sql, (mailid, replyto))
                except pymysql.err.DataError:
                    print(sql % (mailid, replyto))
                    raise

        if references:
            for ref in references.replace('><', '> <').split():
                sql = ('INSERT INTO `reference` '
                       '(`from`, `to_message_id`) '
                       'VALUES (%s, %s)')
                try:
                    cur.execute(sql, (mailid, ref))
                except pymysql.err.DataError:
                    print(sql % (mailid, ref))
                    raise

    sql = ('INSERT INTO `mbox` '
           '(`list`, `mail`) '
           'VALUES (%s, %s)')
    cur.execute(sql, (listid, mailid))

    action = 'STORE'

    log('mbox', action, number, msgno, msgid)


def initialize_list(group):
    sql = ('SELECT `id` FROM `list` '
           'WHERE `name` = %s '
           'LIMIT 1')
    cur.execute(sql, (group,))
    listid = cur.fetchone()

    if not listid:
        sql = ('INSERT INTO `list` '
               '(`name`) '
               'VALUES (%s)')
        cur.execute(sql, (group,))
        listid = cur.lastrowid

    return listid


def update_references():
    sql = ('SELECT `id`, `to_message_id` from `reference` '
           'WHERE `to` IS NULL')

    if cur.execute(sql, ()) > 0:
        fromid, msgid = cur.fetchone()
        refid = lookup_mail(msgid)
        if refid:
            # message found in mail table
            sql = ('UPDATE `reference` '
                   'SET `to`=%s '
                   'WHERE `from`=%s')
            cur.execute(sql, (refid, fromid))


def update_in_reply_to():
    sql = ('SELECT `id`, `replyto_message_id` from `in_reply_to` '
           'WHERE `replyto` IS NULL')

    if cur.execute(sql, ()) > 0:
        mailid, msgid = cur.fetchone()
        replytoid = lookup_mail(msgid)
        if replytoid:
            # message found in mail table
            sql = ('UPDATE `in_reply_to` '
                   'SET `replyto`=%s '
                   'WHERE `mail`=%s')
            cur.execute(sql, (replytoid, mailid))


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
            if keep_going:
                pass
            else:
                raise

    # actually retrieve the messages
    length = len(stack)
    count = 0

    print("Retrieving %d messages." % length)

    while stack:
        count += 1
        status = str(int(100 * count / length)) + ' %'
        msgno = stack.pop()

        try:
            store(listid, nntpconn, msgno)
        except:
            traceback.print_exc()
            if keep_going:
                pass
            else:
                raise

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
    parser.add_argument("-r",
                        "--update-references",
                        help="only update references in database",
                        action="store_true")
    parser.add_argument("groups", default="[]", nargs="*")
    args = parser.parse_args()

    if args.list_groups:
        list_groups()
        return

    aggressive = args.aggressive

    update_in_reply_to()
    update_references()

    if args.update_references:
        return

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

    update_in_reply_to()
    update_references()


if __name__ == "__main__":
    main()
