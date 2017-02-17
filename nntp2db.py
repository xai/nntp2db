#!/usr/bin/env python3
#
# Distributed under terms of the MIT license.
#
# Copyright (c) 2017 Olaf Lessenich
#

import argparse
import email
import email.policy
import json
import logging
import nntplib
import pymysql
import pytz
import time
import traceback


""" Logging setup """
logging.basicConfig(filename='nntp2db.log', level=logging.DEBUG)
console = logging.StreamHandler()
console.setLevel(logging.INFO)

# set a format which is simpler for console use
formatter = logging.Formatter('%(name)-12s: %(levelname)-8s %(message)s')
# tell the handler to use this format
console.setFormatter(formatter)
# add the handler to the root logger
logging.getLogger('').addHandler(console)

""" General setup """
status = '0 %'
attempts = 2  # number of attempts in case of temporary error
aggressive = False
keep_going = False
quiet = False
config = json.load(open('config.json'))

db = pymysql.connect(host=config['host'],
                     user=config['user'],
                     passwd=config['passwd'],
                     db=config['db'],
                     charset=config['charset'],
                     autocommit=config['autocommit'])
cur = db.cursor()


def print_status(target, action, number, msgno, msgid):
    if not quiet:
        print('%5s | %-4s | %-5s | %d(%s): %s' % (status, target, action,
                                                  number, msgno, msgid))


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
            logging.warn('%d: Temporary error. Sleep 5 seconds and retry.'
                         % msgno)
            if not aggressive:
                time.sleep(5)
            pass
        else:
            break
    else:
        logging.warn('%d: Failed to stat after %d attempts'
                     % (msgno, attempts))
        raise Exception('%d: Failed to stat after %d attempts'
                        % (msgno, attempts))

    print_status('nntp', 'STAT', number, msgno, msgid)
    return number, msgid


def get(nntpconn, msgno):
    for attempt in range(attempts):
        try:
            resp, info = nntpconn.article(str(msgno))
        except nntplib.NNTPTemporaryError:
            logging.warn('%d: Temporary error. Sleep 5 seconds and retry.'
                         % msgno)
            if not aggressive:
                time.sleep(5)
            pass
        else:
            break
    else:
        logging.warn('%d: Failed to download after %d attempts'
                     % (msgno, attempts))
        raise Exception('%d: Failed to download after %d attempts'
                        % (msgno, attempts))

    print_status('nntp', 'GET', info.number, msgno, info.message_id)
    return(info.number, info.message_id, info.lines)


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

    print_status('db', action, number, msgno, msgid)
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


def slice_mail(lines):
    # parse mail
    header = list()
    body = list()
    isbody = False

    for line in lines:
        if isbody:
            body.append(line)
            continue
        elif line == b'':
            isbody = True

        header.append(line)

    return b'\r\n'.join(header), b'\r\n'.join(body)


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


def store(listid, nntp_msgid, msg, header, body):
    msgid = msg.get('Message-Id')
    assert nntp_msgid == msgid

    if contains(listid, msgid):
        return

    subject = msg.get('Subject')[:1023]
    lines = msg.get('Lines')

    mailid = lookup_mail(msgid)

    if not mailid:
        sender = email.utils.parseaddr(msg.get('From'))
        senderid = lookup_person(*sender)

        utc_date, tz = parse_date(msg)

        # these contain lists  of realname, addr tuples
        tos = msg.get_all('to', [])
        ccs = msg.get_all('cc', [])

        sql = ('INSERT INTO `mail` '
               '(`message_id`, `subject`, `date`, `timezone`, `from`, '
               '`lines`, `header`, `content`) '
               'VALUES (%s, %s, %s, %s, %s, %s, %s, %s)')
        cur.execute(sql, (msgid, subject, utc_date,
                          tz, senderid, lines,
                          header.decode('ascii', 'ignore'),
                          body.decode('ascii', 'ignore')))
        mailid = cur.lastrowid

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
                    logging.warn(sql % (mailid, replyto))
                    raise

        if references:
            for ref in references.replace('><', '> <').split():
                sql = ('INSERT INTO `reference` '
                       '(`from`, `to_message_id`) '
                       'VALUES (%s, %s)')
                try:
                    cur.execute(sql, (mailid, ref))
                except pymysql.err.DataError:
                    logging.warn(sql % (mailid, ref))
                    raise

    sql = ('INSERT INTO `mbox` '
           '(`list`, `mail`) '
           'VALUES (%s, %s)')
    cur.execute(sql, (listid, mailid))


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
        logging.info('No start message provided, starting at %d' % startnr)

    logging.info("Checking messages %d to %d." % (startnr, last))

    stack = []

    # Check which messages need to be retrieved
    for msgno in reversed(range(startnr, last + 1)):
        try:
            if not aggressive and (msgno % 1000 == 0) and (msgno != startnr):
                logging.info('%d: Sleep 30 seconds' % msgno)
                time.sleep(30)

            if dry_run:
                logging.info('Dry-run: download message no. %d' % msgno)
                continue

            status = str(int(100 * (last - msgno) / (last - startnr))) + ' %'

            if check(listid, nntpconn, msgno, update):
                stack.append(msgno)
            else:
                logging.info('Found a message that is already in the mbox.')
                break

        except Exception as e:
            logging.exception("queue")
            if keep_going:
                pass
            else:
                raise

    # actually retrieve the messages
    length = len(stack)
    count = 0
    failcount = 0

    logging.info("Retrieving %d messages." % length)

    while stack:
        count += 1
        status = str(int(100 * count / length)) + ' %'
        msgno = stack.pop()

        try:
            # retrieve message from nntp server
            number, msgid, lines = get(nntpconn, msgno)
        except:
            pass

        header, body = slice_mail(lines)
        try:
            # parse message and insert into database
            msg = email.message_from_bytes(header + body,
                                           policy=email.policy.default)
            print_status('mbox', "STORE", number, msgno, msgid)
            store(listid, msgid, msg, header, body)
        except Exception as e:
            failcount += 1
            logging.debug('Message:\n' + 80 * '-' + '\n'
                          + (header + body).decode('ascii', 'ignore') + '\n'
                          + 80 * '-')
            logging.exception("retrieve")
            if keep_going:
                print_status('mbox', "FAIL", number, msgno, msgid)
                pass
            else:
                raise

    nntpconn.quit()
    if failcount > 0:
        logging.info('%d messages (%d%%) could not be imported due to defects.'
                     % (failcount, int(100 * failcount / count)))


def main():
    global aggressive
    global console
    global keep_going
    global quiet

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
    parser.add_argument("-k",
                        "--keep-going",
                        help="Keep going in case of errors",
                        action="store_true")
    parser.add_argument("-l",
                        "--list-groups",
                        help="list all available groups and exit",
                        action="store_true")
    parser.add_argument("--log",
                        help="set log level",
                        type=str,
                        default="warning")
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
    parser.add_argument("-q",
                        "--quiet",
                        help="Reduce output on stdout",
                        action="store_true")
    parser.add_argument("groups", default="[]", nargs="*")
    args = parser.parse_args()

    if args.list_groups:
        list_groups()
        return

    aggressive = args.aggressive
    keep_going = args.keep_going
    quiet = args.quiet

    numeric_level = getattr(logging, args.log.upper(), None)
    if not isinstance(numeric_level, int):
            raise ValueError('Invalid log level: %s' % args.log)
    console.setLevel(numeric_level)

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
