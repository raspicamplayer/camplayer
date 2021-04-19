#!/usr/bin/python3

import os
import json
import subprocess

from urllib.parse import urlparse, urlunparse
from utils.logger import LOG
from utils.settings import CONFIG, HEVCMODE
from utils.constants import CONSTANTS
from utils.globals import GLOBALS


class StreamInfo(object):

    _LOG_NAME = "StreamInfo"

    def __init__(self, stream_url):

        # Make absolute paths from relative ones
        if stream_url.startswith('file://.'):
            stream_url = "file://" + os.path.abspath(stream_url.lstrip('file:/'))

        self.url                    = stream_url
        self._cache_file            = CONSTANTS.CACHE_DIR + "streaminfo"
        self.codec_name             = ""
        self.height                 = 0
        self.width                  = 0
        self.framerate              = 0
        self.has_audio              = False
        self.force_udp              = False
        self._parse_stream_details()

        self.valid_url              = self._is_url_valid()
        self.valid_video_windowed   = self._is_video_valid(windowed=True)
        self.valid_video_fullscreen = self._is_video_valid(windowed=False)
        self.weight                 = self._calculate_weight()
        self.quality                = self.width * self.height

        LOG.INFO(self._LOG_NAME, "stream properties '%s', resolution '%ix%i@%i', codec '%s', "
                              "calculated weight '%i', valid url '%i', has audio '%s', "
                              "valid video 'windowed %i fullscreen %i', force UDP '%s'" % (
                                self.printable_url(), self.width, self.height, self.framerate,
                                self.codec_name, self.weight, self.valid_url, self.has_audio,
                                self.valid_video_windowed, self.valid_video_fullscreen, self.force_udp))
        LOG.INFO(self._LOG_NAME, "RUN 'camplayer --rebuild-cache' IF THIS STREAM INFORMATION IS OUT OF DATE!!")

    def printable_url(self):
        """Returns streaming url without readable username and password"""

        parsed = urlparse(self.url)

        if parsed.username or parsed.password:
            parsed = parsed._replace(netloc=str("xxx:yyy@%s:%s" % (parsed.hostname, parsed.port)))

        return urlunparse(parsed)
    
    def _calculate_weight(self):
        """Calculate performance impact for the hardware video decoder"""
        
        if not self.valid_url or (not self.valid_video_windowed and not self.valid_video_fullscreen):
            return 0

        # HEVC decoding does not involve the GPU
        if self.codec_name == "hevc":
            return 0
        
        # OMXplayer plays at min 10FPS
        return self.width * self.height * max(self.framerate, 10)

    def _is_url_valid(self):
        """True when url format is valid"""
        
        if (self.url.startswith('rtsp://') or
                self.url.startswith('http://') or
                self.url.startswith('https://') or
                self.url.startswith('file://')):
            return True
        return False
        
    def _is_video_valid(self, windowed=True):
        """True when the video format is valid for pi hardware"""

        # Model 4 SoC does not support hardware MPEG2 decoding anymore
        omx_mpeg2_support = not "4B" in GLOBALS.PI_MODEL

        if CONFIG.HEVC_MODE == HEVCMODE.AUTO:

            # Model 4 SoC supports hardware HEVC decoding with VLC
            if "4B" in GLOBALS.PI_MODEL:
                CONFIG.HEVC_MODE = HEVCMODE.UHD

            # Model 3+ SoC should be able to decode FHD HEVC in software with VLC
            elif "3B+" in GLOBALS.PI_MODEL:
                CONFIG.HEVC_MODE = HEVCMODE.FHD

            else:
                CONFIG.HEVC_MODE = HEVCMODE.OFF

        # HEVC decoding is currently only supported by VLC,
        # which also means that windowed playback without X11 is not possible right now...
        if not windowed and GLOBALS.VLC_SUPPORT:

            if self.codec_name == 'hevc':
                if CONFIG.HEVC_MODE == HEVCMODE.FHD and \
                        self.width <= 1920 and self.height <= 1080:
                    return True

                if CONFIG.HEVC_MODE == HEVCMODE.UHD and \
                        self.width <= 3840 and self.height <= 2160:
                    return True

            elif self.codec_name == 'mpeg2video':
                if self.width <= 1920 and self.height <= 1080:
                    return True


        # Hardware / OMXplayer supported codecs
        # 1080p is the hard limit of the hardware decoder
        # PI4 does not support MPEG2 in HW
        if (self.codec_name == 'h264' or
                self.codec_name == 'mjpeg' or
                (self.codec_name == 'mpeg2video' and
                 omx_mpeg2_support)) and \
                self.width <= 1920 and \
                self.height <= 1080:
            return True

        return False

    def _parse_stream_details(self):
        """Read stream details from cache file or parse stream directly"""
        
        if not self._is_url_valid():
            return

        parsed_ok = False
        video_found = False
        
        if os.path.isfile(self._cache_file):
            with open(self._cache_file, 'r') as stream_file:
                data = json.load(stream_file)
                
                if self.printable_url() in data.keys():
                    stream_props        = data.get(self.printable_url())
                    self.codec_name     = stream_props.get('codec_name')
                    self.height         = stream_props.get('height')
                    self.width          = stream_props.get('width')
                    self.framerate      = stream_props.get('framerate')
                    self.has_audio      = stream_props.get('audio')
                    self.force_udp      = stream_props.get('force_udp')
                    parsed_ok = True

        if not parsed_ok:
            for i in range(2):

                # Most cameras are using TCP, so test for TCP first. If that fails, test with UDP.
                transport = 'udp' if i > 0 else 'tcp'

                try:
                    ffprobe_args = ['ffprobe', '-v', 'error', '-show_entries',
                                    'stream=codec_type,height,width,codec_name,bit_rate,max_bit_rate,avg_frame_rate',
                                    self.url]

                    if self.url.startswith('rtsp://'):
                        ffprobe_args.extend(['-rtsp_transport', transport])

                    # Invoke ffprobe, 20s timeout required for pi zero
                    streams = subprocess.check_output(ffprobe_args, universal_newlines=True, timeout=10,
                                                      stderr=subprocess.STDOUT).split("[STREAM]")

                    for stream in streams:
                        streamprops = stream.split()

                        if "codec_type=video" in stream and not video_found:
                            video_found = True

                            for streamproperty in streamprops:
                                if "codec_name" in streamproperty:
                                    self.codec_name = streamproperty.split("=")[1]
                                if "height" in streamproperty:
                                    self.height = int(streamproperty.split("=")[1])
                                if "width" in streamproperty:
                                    self.width = int(streamproperty.split("=")[1])
                                if "avg_frame_rate" in streamproperty:
                                    try:
                                        framerate = streamproperty.split("=")[1]

                                        # ffprobe returns framerate as fraction,
                                        # a zero division exception is therefore possible
                                        self.framerate = int(
                                            framerate.split("/")[0])/int(framerate.split("/")[1])
                                    except Exception:
                                        self.framerate = 0

                        elif "codec_type=audio" in stream and not self.has_audio:
                            self.has_audio = True

                    if video_found:
                        try:
                            self.force_udp = True if transport == 'udp' else False
                            self._write_stream_details()
                            break

                        # TODO: filter read-only exception
                        except Exception:
                            LOG.ERROR(self._LOG_NAME, "writing ffprobe results to file failed, read only?")

                # TODO: logging exceptions can spawn credentials??
                except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as ex:
                    if i > 0:
                        LOG.ERROR(self._LOG_NAME, "ffprobe exception: %s" % str(ex))

    def _write_stream_details(self):
        """Write stream details to cache file"""
        
        if not self._is_url_valid():
            return
            
        data = {self.printable_url(): {
            'codec_name'    : self.codec_name,
            'height'        : self.height,
            'width'         : self.width,
            'framerate'     : self.framerate,
            'audio'         : self.has_audio,
            'force_udp'     : self.force_udp,
        }}

        # Read stream details file and append our new data
        if os.path.isfile(self._cache_file):
            with open(self._cache_file) as stream_file:
                cur_data = json.load(stream_file)
                data.update(cur_data)

        # Create folder if not exist
        if not os.path.isdir(os.path.dirname(self._cache_file)):
            os.system("mkdir -p %s" % os.path.dirname(self._cache_file))

        # Write stream details to file
        with open(self._cache_file, 'w+') as stream_file:
            json.dump(data, stream_file, indent=4)
