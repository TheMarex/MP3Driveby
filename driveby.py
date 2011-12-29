#!/usr/bin/python

import os
import sys
import pcapy
from impacket import ImpactDecoder
import hashlib
import threading
import time
import shutil
from mutagen.easyid3 import EasyID3
from mutagen.mp3 import MP3

#INTERFACE = 'eth0'
INTERFACE = 'wlan0'
HOME_DIR = os.environ['HOME']
AUDIO_DIR = os.path.join(HOME_DIR, "Musik")

class Sorter(threading.Thread):
    _files = None
    _exit = False

    def __init__(self):
        threading.Thread.__init__(self)
        
        self.deamon = True
        self._files = []

    def _process(self, f):
        audio = MP3(f)
        bitrate = audio.info.bitrate 
        if bitrate < 128:
            print "WARNING: Low bitrate %i" % bitrate
        id3 = None
        try:
            id3 = EasyID3(f)
        except:
            print "WARNING: No ID3 tags found."

        if id3:
            title = "Unknown"
            artist = "Unknown"
            album = "Unknown"
            try:
                title = id3['title'][0].replace("/", "-")
            except:
                pass
            try:
                artist = id3['artist'][0].replace("/", "-")
            except:
                pass
            try:
                album = id3['album'][0].replace("/", "-")
            except:
                pass
            name = "%s - %s.mp3" % (artist, title)
            folder = "%s/%s" % (artist, album)
        else:
            name = "Unknown.mp3"
            folder = "Unknown"
        folder = os.path.join(AUDIO_DIR, folder)
        if not os.path.exists(folder):
            os.makedirs(folder)
        dst = os.path.join(folder, name)
        if os.path.exists(dst):
            a = open(f, "r")
            b = open(dst, "r")
            m = hashlib.md5()
            m.update(a.read())
            ha = m.digest()
            m = hashlib.md5()
            m.update(b.read())
            hb = m.digest()
            a.close()
            b.close()
            if ha != hb:
                ext = ""
                i = 1
                buf = os.path.join(folder, ("%i-" % i) + name)
                while os.path.exists(buf):
                    buf = os.path.join(folder, ("%i-" % i) + name)
                    i += 1
                dst = buf
            else:
                print "%s already exists." % dst
                os.remove(f)
                self._files.remove(f)
                return

        print dst
        shutil.copy(f, dst)
        os.remove(f)
        self._files.remove(f)

    def run(self):
        while not self._exit:
            for f in list(self._files):
                self._process(f)
            time.sleep(1)

    def add_file(self, name):
        self._files.append(name)

class Job:
    _buf = None
    _src = ""
    _dst = ""
    _port = 0
    _owner = None

    def __init__(self, owner, src, dst, port):
        self._src = src
        self._dst = dst
        self._port = port
        self._buf = {}
        self._owner = owner

    def handle(self, iph, tcph, payload):
        if self._src != iph.get_ip_src()\
        or self._dst != iph.get_ip_dst()\
        or self._port != tcph.get_th_dport():
            return False

        if tcph.get_FIN():
            self._finished()
            return True
        
        seq = tcph.get_th_seq()
        if payload.startswith("HTTP"):
            payload = payload.split("\r\n")
            i = 0
            while payload[i] != "":
                i += 1
            payload = payload[i+1]
        self._buf[seq] = payload

        return True

    def _finished(self):
        data = ""
        for s in sorted(self._buf):
            data += self._buf[s]

        m = hashlib.md5()
        m.update(data)
        name = m.hexdigest()[:9]
        dst = "/tmp/%s.mp3" % name
        f = open(dst, "wb")
        f.write(data)
        f.close()

        self._owner.job_finished(self, dst)

class AudioCapture:
    _cap = None
    _decoder = None
    _jobs = None
    _sorter = None
    _next = False

    def __init__(self, interface):
        self._cap = pcapy.open_live(interface, 0xFFFF, 0, 0)
        os.setgid(1000)
        os.setuid(1000)
        self._cap.setfilter('ip proto \\tcp')
        self._decoder = ImpactDecoder.EthDecoder()

        self._jobs = []
        self._next = False
        self._sorter = Sorter()
        self._sorter.start()

        print "Listening."
        try:
            self._cap.loop(-1, self._got_packet)
        except KeyboardInterrupt:
            while len(self._sorter._files) > 0:
                time.sleep(1)
            print "Exit!"
            self._sorter._exit = True
            self._sorter.join()
            sys.exit()
                

    def _is_audio(self, http):
        if "Content-Type: audio" in http:
            return True
        return False

    def _is_post(self, http):
        p = "/stream.php"
        if p in http:
            return True
        return False

    def job_finished(self, job, dst):
        self._jobs.remove(job)
        self._sorter.add_file(dst)

    def _got_packet(self, header, data):
        ether = self._decoder.decode(data)
        iph = ether.child()
        tcph = iph.child()
        l = tcph.get_th_off()*4
        payload = tcph.get_packet()[l:] 
        src = iph.get_ip_src()
        dst = iph.get_ip_dst()

        if self._is_post(payload):
            print "Got post!"
            self._next = True
        elif self._is_audio(payload) and self._next:
            print "Found audio!"
            self._next = False
            port = tcph.get_th_dport()
            job = Job(self, src, dst, port)
            self._jobs.append(job)
            job.handle(iph, tcph, payload)
        else:
            for job in list(self._jobs):
                if job.handle(iph, tcph, payload):
                    break

cap = AudioCapture(INTERFACE)

