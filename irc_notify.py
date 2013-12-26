#!/usr/bin/env python
import re
import time
import yaml
import kombu
from kombu import BrokerConnection
import socket
import argparse
import sys

# Platform conditional imports
if sys.platform.startswith('linux'):
    import pynotify
    PLATFORM='linux'
elif sys.platform.startswith('darwin'):
    import subprocess
    import StringIO
    PLATFORM='osx'
else:
    print "Unsupported sys.platform: %s" % sys.platform
    sys.exit(1)

from pprint import PrettyPrinter
pp = PrettyPrinter(indent=4)

class MessageHandler(object):
    '''Handle unserialized messages from amqp_notify'''

    def _send_to_notifyosd(self, title, message):
        '''Send an alert to Notify-OSD via pynotify'''
        print "Alerting with message: %s %s" % (title, message)
        n = pynotify.Notification(title, message, 'notification-message-im')
        n.set_urgency('critical')
        n.show()

    def _send_to_growl(self, title, message):
        '''Send an alert to Growl via Growlnotify'''
        print "Alerting with message: %s %s" % (title, message)
        echo = subprocess.Popen(['echo', message], stdout=subprocess.PIPE)
        growlnotify = subprocess.Popen(['growlnotify', title], stdin=echo.stdout)
        echo.stdout.close()

    def __init__(self):
        if PLATFORM == 'linux':
            # Init pynotify
            pynotify.init('irc_notify.py')
            self.send_alert = self._send_to_notifyosd
        elif PLATFORM == 'osx':
            self.send_alert = self._send_to_growl
        else:
            print "Upsupported PLATFORM: %s" % PLATFORM
            sys.exit(1)


    def private_handler(self, msg):
        '''Handle hilights in private messages and query windows'''
        check_day_changed = re.search('^Day changed to', msg[':message'])
        check_back_on_server = re.search('is back on server$', msg[':message'])

        if check_day_changed or check_back_on_server:
            return

        title = '%s/%s' % (msg[':server'], msg[':channel'])
        message = msg[':message']

        self.send_alert(title, message)

    def channel_handler(self, msg):
        '''Handle hilights (nick mentions, hilight rules) in public channels'''
        # Date in message?
        nick_tag = filter(lambda x: x.startswith('nick_'), msg[':tags'])[0]
        nick = nick_tag.replace('nick_', '', 1)
        title = '%s/%s - %s' % (msg[':server'], msg[':channel'], nick)
        message = '%s' % (msg[':message'])

        self.send_alert(title, message)

    def catch_all_handler(self, msg):
        print "Got unparsable message"
        pp.pprint(msg)
        print "end unparsable message"

    HANDLERS = {
        'channel': channel_handler,
        'private': private_handler,
    }

    def handle_message(self, msg):
        '''Route message based on :type'''
        if 'notify_none' in msg[':tags'] or 'no_highlight' in msg[':tags']:
            print "Ignoring"
            return
        handler = self.HANDLERS.get(msg[':type'], self.catch_all_handler)
        handler(self, msg)


p = argparse.ArgumentParser()
p.add_argument('-H', '--host', default='localhost', help='Rabbitmq host')
p.add_argument('-P', '--port', default=5672, help='Rabbitmq port')
p.add_argument('-u', '--user', default='guest', help='Rabbitmq user')
p.add_argument('-p', '--password', default='guest', help='Rabbitmq password')
p.add_argument('-e', '--exchange', default='chat-notify', help='Rabbitmq exchange')
p.add_argument('-q', '--queue', default='irc-notify-queue', help='Rabbitmq queue')
args = p.parse_args()

conn_string = 'amqp://%s:%s@%s:%s' % (args.user, args.password, args.host, args.port)

# TODO: declare queues if missing?
try:
    # Maintain connection to rabbitmq
    while True:
        try:
            conn = BrokerConnection(conn_string)
            ch = conn.channel()
            sq = conn.SimpleQueue(args.queue)
        except socket.error:
            print 'Rabbitmq at %s unavailable, trying again in 30s' % conn_string
            time.sleep(30)
            continue

        # Fetch and process messages
        while True:
            try:
                m = sq.get()
            except IOError, e:
                if e.message == 'Socket closed':
                    print 'Rabbitmq socket closed, reconnecting'
                    time.sleep(30)
                    break
                else:
                    raise e

            try:
                msg = yaml.load(m.body)
            except:
                print "I have no idea what to do with: %s" % m.body
                m.ack()
                continue

            handler = MessageHandler()
            handler.handle_message(msg)

            m.ack()
except KeyboardInterrupt:
    pass
