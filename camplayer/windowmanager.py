#!/usr/bin/python3

import subprocess
import os
import time
import signal
import threading
import sys
import math

from enum import IntEnum
from enum import unique

from utils import utils
from utils.logger import LOG
from utils.settings import CONFIG, STREAMQUALITY, AUDIOMODE
from utils.constants import CONSTANTS
from utils.globals import GLOBALS
from streaminfo import StreamInfo


@unique
class PLAYSTATE(IntEnum):
    NONE    = 0     # Nothing is playing
    INIT1   = 1     # Player starting
    INIT2   = 2     # Player started (PID assigned) but video still loading/buffering
    PLAYING = 3     # Player stated and video playing
    BROKEN  = 4     # Player video stream broken

@unique
class PLAYER(IntEnum):
    NONE        = 0
    OMXPLAYER   = 1
    VLCPLAYER   = 2


class DBUS_COMMAND(object):
    PLAY_STATUS         = "PlaybackStatus"
    PLAY_DURATION       = "Duration"
    PLAY_POSITION       = "Position"
    PLAY_STOP           = "Stop"
    PLAY_PLAY           = "OpenUri"
    PLAY_VOLUME         = "Volume"
    OMXPLAYER_VIDEOPOS  = "VideoPos"
    OMXPLAYER_LAYER     = "SetLayer"


class Window(object):

    # TODO Camplayer 2
    # * Drop OMXplayer support and switch completely to VLC
    # * Add windowed playback support for VLC
    # * Drop all hacks introduced to support both players
    # * Refactor audio support

    _LOG_NAME = "Window"

    # Holds all player PIDs and
    # associated command line arguments
    _player_pid_pool_cmdline = [[], []]

    # VLC is currently only supported for fullscreen playback
    # so only one instance can exist for each display
    _vlc_dbus_ident             = [""       for _ in range(GLOBALS.NUM_DISPLAYS)]
    _vlc_active_stream_url      = [""       for _ in range(GLOBALS.NUM_DISPLAYS)]
    _vlc_subs_enabled           = [False    for _ in range(GLOBALS.NUM_DISPLAYS)]
    vlc_player_pid              = [0        for _ in range(GLOBALS.NUM_DISPLAYS)]

    # Active estimated decoder weight for all windows
    _total_weight = 0
    
    def __init__(self, x1, y1, x2, y2, gridindex, screen_idx, window_idx, display_idx):

        self.x1                 = x1                        # Upper left x-position of window
        self.y1                 = y1                        # Upper left y-position of window
        self.x2                 = x2                        # Lower right x-position of window
        self.y2                 = y2                        # Lower right y-position of window
        self.gridindex          = gridindex                 # Grid indices covered by this window
        self.omx_player_pid     = 0                         # OMXplayer  PID
        self._omx_audio_enabled = False                     # OMXplayer audio stream enabled
        self._omx_duration      = 0                         # OMXplayer reported stream duration
        self._layer             = 0                         # Player dispmanx layer
        self.visible            = False                     # Is window in visible area?
        self._forced_fullscreen  = self.native_fullscreen   # Is window forced in fullscreen mode?
        self._fail_rate_hr      = 0                         # Stream failure rate of last hour
        self._time_playstatus   = 0                         # Timestamp of last playstatus check
        self._time_streamstart  = 0                         # Timestamp of last stream start
        self.streams            = []                        # Assigned stream(s)
        self.active_stream      = None                      # Currently playing stream
        self._display_name      = ""                        # Video OSD display name
        self._player            = PLAYER.NONE               # Currently active player for this window (OMX or VLC)
        self.playstate          = PLAYSTATE.NONE            # Current stream play state for this window
        self._window_num        = window_idx + 1
        self._screen_num        = screen_idx + 1
        self._display_num       = display_idx + 1
        self.force_udp          = False

        self._omx_dbus_ident = str("org.mpris.MediaPlayer2.omxplayer_D%02d_S%02d_W%02d" %
                                   (self._display_num, self._screen_num, self._window_num))
        
        LOG.DEBUG(self._LOG_NAME,
                  "init window with position '%i %i %i %i', gridindex '%s', "
                  "omxplayer dbus name '%s'"
                  % (x1, y1, x2, y2, str(gridindex), self._omx_dbus_ident))

    def add_stream(self, url):
        """Add a stream URL to this window"""

        if not url:
            return

        self.streams.append(StreamInfo(url))

    def set_display_name(self, display_name):
        """Set player OSD text for this window"""

        if not display_name or self._display_name:
            return

        sub_file = CONSTANTS.CACHE_DIR + display_name + ".srt"

        try:
            # Create folder if not exist
            if not os.path.isdir(os.path.dirname(sub_file)):
                os.system("mkdir -p %s" % os.path.dirname(sub_file))

            # Create subtitle file if not exist
            if not os.path.isfile(sub_file):
                with open(sub_file, 'w+') as file:
                    # Important note: we can only show subs for a 99 hour period!
                    file.write('00:00:00,00 --> 99:00:00,00\n')
                    file.write(display_name + '\n')

            self._display_name = display_name
        except:

            # TODO: filter for read-only error only
            LOG.ERROR(self._LOG_NAME, "writing subtitle file failed, read only?")

    @property
    def native_fullscreen(self):
        """Is this window the same size as the configured screen?"""

        return self.x1 == CONSTANTS.VIRT_SCREEN_OFFSET_X and \
                self.y1 == CONSTANTS.VIRT_SCREEN_OFFSET_Y and \
                self.x2 == CONSTANTS.VIRT_SCREEN_OFFSET_X + CONSTANTS.VIRT_SCREEN_WIDTH and \
                self.y2 == CONSTANTS.VIRT_SCREEN_OFFSET_Y + CONSTANTS.VIRT_SCREEN_HEIGHT

    @property
    def fullscreen_mode(self):
        """Is this window the same size as the configured screen?"""

        return self.native_fullscreen or self._forced_fullscreen

    @fullscreen_mode.setter
    def fullscreen_mode(self, value):
        self._forced_fullscreen = value

    @property
    def playtime(self):
        """Get playtime in seconds"""

        return time.monotonic() - self._time_streamstart

    @property
    def window_width(self):
        """Get the window width"""
        
        return int(self.x2 - self.x1)

    @property
    def window_height(self):
        """Get the window height"""
        
        return int(self.y2 - self.y1)
        
    def get_weight(self, stream=None):
        """Get decoder weight for the current/default stream"""

        if stream:
            pass
        elif self.active_stream:
            stream = self.active_stream
        else:
            stream = self.get_default_stream()

        if stream:
            return stream.weight

        return 0

    def get_lowest_quality_stream(self, windowed=None):
        """Get the lowest quality stream/subchannel"""

        if len(self.streams) <= 0:
            return None

        if self.native_fullscreen:
            windowed = False
        elif windowed is None:
            windowed = not self.fullscreen_mode

        stream = None

        quality = sys.maxsize

        # Select the lowest valid resolution stream by default
        for strm in self.streams:

            video_valid = strm.valid_video_fullscreen \
                if not windowed else strm.valid_video_windowed

            if quality > strm.quality > 10000 and video_valid:
                quality = strm.quality
                stream = strm

        return stream

    def get_highest_quality_stream(self, prevent_downscaling=False, windowed=None):
        """Get the highest quality stream/subchannel"""

        if len(self.streams) <= 0:
            return None

        if self.native_fullscreen:
            windowed = False
        elif windowed is None:
            windowed = not self.fullscreen_mode

        stream = None

        window_width = CONSTANTS.VIRT_SCREEN_WIDTH if not windowed else self.window_width
        window_height = CONSTANTS.VIRT_SCREEN_HEIGHT if not windowed else self.window_height

        # Select the highest valid resolution
        for strm in self.streams:

            video_valid = strm.valid_video_fullscreen \
                if not windowed else strm.valid_video_windowed

            if strm.quality > 10000 and video_valid:

                if not stream:
                    stream = strm

                # Downscaling is costly (GPU), much more than upscaling...
                if prevent_downscaling:

                    if strm.height > stream.height and strm.height <= window_height:
                        stream = strm

                    elif strm.height < stream.height and stream.height > window_height:
                        stream = strm

                else:

                    if strm.height > stream.height and stream.height < window_height:
                        stream = strm

                    # It makes no sense to select a too large resolution.
                    # e.g. We have two streams, one 480p and one 1080p.
                    #   Let's assume our playback window is 360 pixels high,
                    #   then we want to select the 480p stream instead of the 1080p one.
                    elif strm.height < stream.height and strm.height >= window_height:
                        stream = strm

        return stream

    def get_default_stream(self, windowed=None):
        """Get the default stream based on the used configuration"""

        if len(self.streams) <= 0:
            return None

        if self.native_fullscreen:
            windowed = False
        elif windowed is None:
            windowed = not self.fullscreen_mode

        stream = None

        if CONFIG.STREAM_QUALITY == STREAMQUALITY.LOW:
            stream = self.get_lowest_quality_stream(windowed=windowed)

        elif CONFIG.STREAM_QUALITY == STREAMQUALITY.HIGH:
            stream = self.get_highest_quality_stream(windowed=windowed)

        elif CONFIG.STREAM_QUALITY == STREAMQUALITY.AUTO:

            # Downscaling is costly (GPU), much more than upscaling...
            # A perfect resolution match is the best.
            stream = self.get_highest_quality_stream(prevent_downscaling=True, windowed=windowed)

        return stream
        
    def stream_set_visible(self, _async=False, fullscreen=None):
        """Set an active off screen stream back on screen"""

        if self._player == PLAYER.VLCPLAYER \
                and not self.get_vlc_pid(self._display_num):
            return

        if self.playstate == PLAYSTATE.NONE:
            return

        if fullscreen is None:
            fullscreen = self.fullscreen_mode

        if not self.visible or (fullscreen != self.fullscreen_mode):

            LOG.INFO(self._LOG_NAME, "stream set visible '%s' '%s'" %
                     (self._omx_dbus_ident, self.active_stream.printable_url()))

            self.fullscreen_mode = fullscreen

            if self._player == PLAYER.OMXPLAYER:
                # OMXplayer instance is playing outside the visible screen area.
                # Sending the position command will move this instance into the visible screen area.

                if fullscreen:
                    videopos_arg = str("%i %i %i %i" % (CONSTANTS.VIRT_SCREEN_OFFSET_X, CONSTANTS.VIRT_SCREEN_OFFSET_Y,
                                                        CONSTANTS.VIRT_SCREEN_OFFSET_X + CONSTANTS.VIRT_SCREEN_WIDTH,
                                                        CONSTANTS.VIRT_SCREEN_OFFSET_Y + CONSTANTS.VIRT_SCREEN_HEIGHT))
                else:
                    videopos_arg = str("%i %i %i %i" % (self.x1, self.y1, self.x2, self.y2))

                # Re-open OMXplayer with the audio stream enabled
                if CONFIG.AUDIO_MODE == AUDIOMODE.FULLSCREEN and fullscreen \
                        and not self._omx_audio_enabled and self.active_stream.has_audio:
                    self.visible = True
                    self.stream_refresh()
                    return

                # Re-open OMXplayer with the audio stream disabled
                if self._omx_audio_enabled and not fullscreen:
                    self.visible = True
                    self.stream_refresh()
                    return

                if _async:
                    setvisible_thread = threading.Thread(
                        target=self._send_dbus_command,
                        args=(DBUS_COMMAND.OMXPLAYER_VIDEOPOS, videopos_arg,))

                    setvisible_thread.start()
                else:
                    self._send_dbus_command(DBUS_COMMAND.OMXPLAYER_VIDEOPOS, videopos_arg)

            elif fullscreen:
                # VLC player instance can be playing or in idle state.
                # Sending the play command will start fullscreen playback of our video/stream.
                # When VLC is playing other content, we will hijack it.

                # Start our stream
                self._send_dbus_command(DBUS_COMMAND.PLAY_PLAY)

                # Pretend like the player just started again
                self.playstate = PLAYSTATE.INIT2
                self._time_streamstart = time.monotonic()

                # Mark our steam as the active one for this display
                Window._vlc_active_stream_url[self._display_num - 1] = self.active_stream.url

            else:
                # Windowed with VLC not supported -> stop video
                self.stream_stop()

        self.visible = True
        
    def stream_set_invisible(self, _async=False):
        """Keep the stream open but set it off screen"""

        if self.playstate == PLAYSTATE.NONE:
            return

        if self.visible:
            LOG.INFO(self._LOG_NAME, "stream set invisible '%s' '%s'" %
                     (self._omx_dbus_ident, self.active_stream.printable_url()))

            if self._player == PLAYER.OMXPLAYER:
                # OMXplayer instance is playing inside the visible screen area.
                # Sending the position command with offset will move this instance out of the visible screen area.

                if self._omx_audio_enabled:
                    self.visible = False
                    self.stream_refresh()
                    return

                videopos_arg = str("%i %i %i %i" % (
                    self.x1 + CONSTANTS.WINDOW_OFFSET, self.y1,
                    self.x2 + CONSTANTS.WINDOW_OFFSET, self.y2))

                if _async:
                    setinvisible_thread = threading.Thread(
                        target=self._send_dbus_command,
                        args=(DBUS_COMMAND.OMXPLAYER_VIDEOPOS, videopos_arg,))

                    setinvisible_thread.start()
                else:
                    self._send_dbus_command(DBUS_COMMAND.OMXPLAYER_VIDEOPOS, videopos_arg)

            else:

                # It's possible that another window hijacked our vlc instance, so do not send 'stop' then.
                if self.active_stream.url == Window._vlc_active_stream_url[self._display_num - 1]:
                    self._send_dbus_command(DBUS_COMMAND.PLAY_STOP)
                    Window._vlc_active_stream_url[self._display_num - 1] = ""

        self.visible = False

    def get_stream_playstate(self):
        """
        Get and update the stream's playstate,
        don't use this time consuming method too often,
        use 'self.playstate' when you can.
        """

        if self.playstate == PLAYSTATE.NONE:
            return self.playstate

        # Allow at least 1 second for the player to startup
        if self.playstate == PLAYSTATE.INIT1 and self.playtime < 1:
            return self.playstate

        old_playstate = self.playstate

        # Assign the player PID
        if self.playstate == PLAYSTATE.INIT1:

            if self._player == PLAYER.VLCPLAYER:
                pid = self.get_vlc_pid(self._display_num)
            else:
                pid = self.get_omxplayer_pid()

            if pid > 0:
                if self._player == PLAYER.VLCPLAYER:
                    Window.vlc_player_pid[self._display_num - 1] = pid
                else:
                    self.omx_player_pid = pid

                self.playstate = PLAYSTATE.INIT2

                LOG.DEBUG(self._LOG_NAME, "assigned PID '%i' for stream '%s' '%s'" %
                          (pid, self._omx_dbus_ident, self.active_stream.printable_url()))

            elif self.playtime > CONSTANTS.PLAYER_INITIALIZE_MS / 1000:
                self.playstate = PLAYSTATE.BROKEN

        # Check if the player is actually playing media
        # DBus calls are time consuming, so limit them
        elif time.monotonic() > (self._time_playstatus + 10) or \
                (self.playstate == PLAYSTATE.INIT2 and time.monotonic() > (self._time_playstatus + 1)):

            LOG.DEBUG(self._LOG_NAME, "fetching playstate for stream '%s' '%s'" %
                      (self._omx_dbus_ident, self.active_stream.printable_url()))

            duration_diff = 0
            output = ""

            # Check playstate and kill the player if it does not respond properly
            # 04/04/2020: Under some circumstances omxplayer freezes with corrupt streams (bad wifi/network quality etc.),
            # while it still reports its playstate as 'playing',
            # therefore we monitor will monitor the reported 'duration' (for livestreams) from now on.
            if not self.active_stream.url.startswith('file://') and self._player == PLAYER.OMXPLAYER:

                output = self._send_dbus_command(
                    DBUS_COMMAND.PLAY_DURATION, kill_player_on_error=self.playtime > CONFIG.PLAYTIMEOUT_SEC)

                try:
                    duration = int(output.split("int64")[1].strip())
                    duration_diff = duration - self._omx_duration
                    self._omx_duration = duration
                except Exception:
                    self._omx_duration = 0

            else:
                output = self._send_dbus_command(
                    DBUS_COMMAND.PLAY_STATUS, kill_player_on_error=self.playtime > CONFIG.PLAYTIMEOUT_SEC)

            if (output and "playing" in str(output).lower()) or duration_diff > 0:
                self.playstate = PLAYSTATE.PLAYING

            else:
                # Only set broken after a timeout period,
                # so keep the init state the first seconds
                if self.playtime > CONFIG.PLAYTIMEOUT_SEC:

                    if self._player == PLAYER.OMXPLAYER or self.visible:
                        # Don't set broken when VLC is in "stopped" state
                        # Stopped state occurs when not visible

                        self.playstate = PLAYSTATE.BROKEN
                
            self._time_playstatus = time.monotonic()

        if old_playstate != self.playstate:
            LOG.INFO(self._LOG_NAME, "stream playstate '%s' for stream '%s' '%s'" %
                     (self.playstate.name, self._omx_dbus_ident, self.active_stream.printable_url()))

        return self.playstate

    def _send_dbus_command(self, command, argument="", kill_player_on_error=True, retries=CONSTANTS.DBUS_RETRIES):
        """Send command to player with DBus"""

        response = ""
        command_destination = ""
        command_prefix = ""

        if self._player == PLAYER.OMXPLAYER:
            command_destination = self._omx_dbus_ident

            # OMXplayer needs some environment variables
            command_prefix = str("export DBUS_SESSION_BUS_ADDRESS=`cat /tmp/omxplayerdbus.%s` && "
                                 "export DBUS_SESSION_BUS_PID=`cat /tmp/omxplayerdbus.%s.pid` && "
                                 % (GLOBALS.USERNAME, GLOBALS.USERNAME))

        elif self._player == PLAYER.VLCPLAYER:
            command_destination = Window._vlc_dbus_ident[self._display_num - 1]

            # VLC changes its DBus string to 'org.mpris.MediaPlayer2.vlc.instancePID'
            # when opening a second instance, so we have to append this PID first.
            if 'instance' in command_destination:
                command_destination += str(Window.vlc_player_pid[self._display_num - 1])

        for i in range(retries + 1):
            try:
                if command == DBUS_COMMAND.OMXPLAYER_VIDEOPOS:
                    response = subprocess.check_output(
                        command_prefix + "dbus-send --print-reply=literal --reply-timeout=%i "
                                         "--dest=%s /org/mpris/MediaPlayer2 "
                                         "org.mpris.MediaPlayer2.Player.%s objpath:/not/used "
                                         "string:'%s'" % (CONSTANTS.DBUS_TIMEOUT_MS, command_destination,
                                        command, argument), shell=True, stderr=subprocess.STDOUT).decode().strip()

                elif command == DBUS_COMMAND.PLAY_STOP:
                    response = subprocess.check_output(
                        command_prefix + "dbus-send --print-reply=literal --reply-timeout=%i "
                                         "--dest=%s /org/mpris/MediaPlayer2 "
                                         "org.mpris.MediaPlayer2.Player.%s" %
                                        (CONSTANTS.DBUS_TIMEOUT_MS, command_destination, command),
                                        shell=True, stderr=subprocess.STDOUT).decode().strip()

                elif command == DBUS_COMMAND.PLAY_PLAY:
                    response = subprocess.check_output(
                        command_prefix + "dbus-send --print-reply=literal --reply-timeout=%i "
                                         "--dest=%s /org/mpris/MediaPlayer2 "
                                         "org.mpris.MediaPlayer2.Player.%s string:'%s'" %
                                        (CONSTANTS.DBUS_TIMEOUT_MS, command_destination, command,
                                         self.active_stream.url),
                                        shell=True, stderr=subprocess.STDOUT).decode().strip()

                elif command == DBUS_COMMAND.PLAY_VOLUME:
                    response=subprocess.check_output(
                        command_prefix + "dbus-send --print-reply=literal --reply-timeout=%i "
                                         "--dest=%s /org/mpris/MediaPlayer2 "
                                         "org.freedesktop.DBus.Properties.Set "
                                         "string:'org.mpris.MediaPlayer2.Player' string:'%s' variant:double:%f" %
                                        (CONSTANTS.DBUS_TIMEOUT_MS, command_destination, command, argument),
                                        shell=True, stderr=subprocess.STDOUT).decode().strip()

                else:
                    response = subprocess.check_output(
                        command_prefix + "dbus-send --print-reply=literal --reply-timeout=%i "
                                         "--dest=%s /org/mpris/MediaPlayer2 "
                                         "org.freedesktop.DBus.Properties.Get "
                                         "string:'org.mpris.MediaPlayer2.Player' string:'%s'" %
                                        (CONSTANTS.DBUS_TIMEOUT_MS, command_destination, command),
                                        shell=True, stderr=subprocess.STDOUT).decode().strip()

                LOG.DEBUG(self._LOG_NAME, "DBus response to command '%s:%s %s' is '%s'" %
                          (command_destination, command, argument, response))

            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as ex:

                if i == retries:

                    if self._player == PLAYER.VLCPLAYER:
                        player_pid = Window.vlc_player_pid[self._display_num - 1]
                    else:
                        player_pid = self.omx_player_pid

                    LOG.ERROR(self._LOG_NAME, "DBus '%s' is not responding correctly after '%i' attemps, "
                                              "give up now" % (command_destination, retries + 1))

                    if kill_player_on_error and player_pid > 0:
                        LOG.ERROR(self._LOG_NAME, "DBus '%s' closing the associated player "
                                                  "with PID '%i' now" % (command_destination, player_pid))

                        try:
                            os.kill(player_pid, signal.SIGKILL)
                        except ProcessLookupError:
                            LOG.DEBUG(self._LOG_NAME, "killing PID '%i' failed" % player_pid)

                        self._pidpool_remove_pid(player_pid)

                        if self._player == PLAYER.VLCPLAYER:
                            Window.vlc_player_pid[self._display_num - 1] = 0
                        else:
                            self.omx_player_pid = 0

                else:
                    LOG.WARNING(self._LOG_NAME, "DBus '%s' is not responding correctly, "
                                            "retrying within 250ms" % command_destination)
                    time.sleep(0.25)
                    continue

            break

        return response

    def stream_switch_quality_up(self, check_only=False, limit_default=True):
        """Switch to the next higher quality stream, if any"""

        if self.active_stream and self.playstate != PLAYSTATE.NONE:

            resolution = sys.maxsize
            stream = None

            # Limit max quality to the default for performance reasons
            if limit_default:
                resolution = self.get_default_stream(windowed=not self.fullscreen_mode).quality + 1

            # Select the the next higher resolution stream
            for strm in self.streams:

                video_valid = strm.valid_video_fullscreen \
                    if self.fullscreen_mode else strm.valid_video_windowed

                if resolution > strm.quality > self.active_stream.quality and video_valid:
                    resolution = strm.quality
                    stream = strm

            # The highest quality stream is already playing
            if not stream:
                LOG.INFO(self._LOG_NAME, "highest quality stream already playing")
                return False

            if not check_only:
                self.stream_stop()
                time.sleep(0.1)
                self._stream_start(stream)
            return stream

        return False

    def stream_switch_quality_down(self, check_only=False):
        """Switch to the next lower quality stream, if any"""

        if self.active_stream and self.playstate != PLAYSTATE.NONE:

            resolution = 10000
            stream = None

            # Select the the next lower resolution stream
            for strm in self.streams:

                video_valid = strm.valid_video_fullscreen \
                    if self.fullscreen_mode else strm.valid_video_windowed

                if resolution < strm.quality < self.active_stream.quality and video_valid:
                    resolution = strm.quality
                    stream = strm

            # The lowest quality stream is already playing
            if not stream:
                LOG.INFO(self._LOG_NAME, "lowest quality stream already playing")
                return False

            if not check_only:
                self.stream_stop()
                time.sleep(0.1)
                self._stream_start(stream)

            return stream

        return False

    def stream_refresh(self):
        """Refresh/restart the current stream with the same parameters"""

        if self.playstate == PLAYSTATE.NONE:
            return

        stream = self.active_stream
        self.stream_stop()
        self._stream_start(stream=stream)

    def stream_stop(self):
        """Stop the playing stream"""

        if self.playstate == PLAYSTATE.NONE:
            return

        LOG.INFO(self._LOG_NAME, "stopping stream '%s' '%s'" % (self._omx_dbus_ident, self.active_stream.printable_url()))

        # VLC:
        # - send Dbus stop command, vlc stays idle in the background
        # - not every window has it's own vlc instance as vlc can only be used for fullscreen playback,
        #   therefore we have to be sure that 'our instance' isn't already playing another stream.
        if self._player == PLAYER.VLCPLAYER and \
                Window._vlc_active_stream_url[self._display_num - 1] == self.active_stream.url:

            # Stop playback but do not quit
            self._send_dbus_command(DBUS_COMMAND.PLAY_STOP)

            Window._vlc_active_stream_url[self._display_num - 1] = ""

        # OMXplayer:
        # - omxplayer doen't support an idle state, stopping playback will close omxplayer,
        #   so in this case we also have to cleanup the pids.
        elif self._player == PLAYER.OMXPLAYER and self.omx_player_pid:
            try:
                os.kill(self.omx_player_pid, signal.SIGTERM)
            except Exception as error:
                LOG.ERROR(self._LOG_NAME, "pid kill error: %s" % str(error))

            self._pidpool_remove_pid(self.omx_player_pid)
            self.omx_player_pid = 0

        if self.active_stream:
            Window._total_weight -= self.get_weight(self.active_stream)

        self.active_stream = None
        self.playstate = PLAYSTATE.NONE
        self._omx_duration = 0

    def stream_start(self, visible=None, force_fullscreen=False, force_hq=False):
        """Start streaming in or outside the visible screen"""

        stream = None

        if self.playstate != PLAYSTATE.NONE:
            return

        if visible is not None:
            self.visible = visible

        self.fullscreen_mode = force_fullscreen

        if force_hq:
            stream = self.get_highest_quality_stream()

        self._stream_start(stream=stream)
    
    def _stream_start(self, stream=None):
        """Start the specified stream if any, else the default will be played"""

        if self.playstate != PLAYSTATE.NONE:
            return

        if len(self.streams) <= 0:
            return

        if not stream:
            stream = self.get_default_stream()

        if not stream:
            return

        win_width = CONSTANTS.VIRT_SCREEN_WIDTH if self.fullscreen_mode else self.window_width
        win_height = CONSTANTS.VIRT_SCREEN_HEIGHT if self.fullscreen_mode else self.window_height
        sub_file = ""

        if self._display_name and CONFIG.VIDEO_OSD:
            sub_file = CONSTANTS.CACHE_DIR + self._display_name + ".srt"

        LOG.INFO(self._LOG_NAME, "starting stream '%s' '%s' with resolution '%ix%i' and weight '%i' in a window '%ix%i'"
                 % (self._omx_dbus_ident, stream.printable_url(), stream.width,
                    stream.height, self.get_weight(stream), win_width, win_height))

        # OMXplayer can play in fullscreen and windowed mode
        # One instance per window
        if stream.valid_video_windowed:
            self._player = PLAYER.OMXPLAYER

            # Layer should be unique to avoid visual glitches/collisions
            omx_layer_arg = (self._screen_num * CONSTANTS.MAX_WINDOWS) + self._window_num

            if self.fullscreen_mode and self.visible:
                # Window position also required for fullscreen playback,
                # otherwise lower layers will be disabled when moving the window position later on

                omx_pos_arg = str("%i %i %i %i" % (
                    CONSTANTS.VIRT_SCREEN_OFFSET_X, CONSTANTS.VIRT_SCREEN_OFFSET_Y,
                    CONSTANTS.VIRT_SCREEN_OFFSET_X + CONSTANTS.VIRT_SCREEN_WIDTH,
                    CONSTANTS.VIRT_SCREEN_OFFSET_Y + CONSTANTS.VIRT_SCREEN_HEIGHT))

            else:
                omx_pos_arg = str("%i %i %i %i" % (
                    self.x1 + (0 if self.visible else CONSTANTS.WINDOW_OFFSET), self.y1,
                    self.x2 + (0 if self.visible else CONSTANTS.WINDOW_OFFSET), self.y2
                ))

            player_cmd = ['omxplayer',
                '--no-keys',                                                # No keyboard input
                '--no-osd',                                                 # No OSD
                '--aspect-mode',    'stretch',                              # Stretch video if aspect doesn't match
                '--dbus_name',      self._omx_dbus_ident,                   # Dbus name for controlling position etc.
                '--threshold',      str(CONFIG.BUFFERTIME_MS / 1000),       # Threshold of buffer in seconds
                '--layer',          str(omx_layer_arg),                     # Dispmanx layer
                '--alpha',          '255',                                  # No transparency
                '--nodeinterlace',                                          # Assume progressive streams
                '--nohdmiclocksync',                                        # Clock sync makes no sense with multiple clock sources
                '--display',        '7' if self._display_num == 2 else '2', # 2 is HDMI0 (default), 7 is HDMI1 (pi4)
                '--timeout',        str(CONFIG.PLAYTIMEOUT_SEC),            # Give up playback after this period of trying
                '--win',            omx_pos_arg                             # Window position
            ]

            if not self.force_udp and not stream.force_udp:
                player_cmd.extend(['--avdict', 'rtsp_transport:tcp'])       # Force RTSP over TCP

            if stream.url.startswith('file://'):
                player_cmd.append('--loop')                                 # Loop for local files (demo/test mode)
            else:
                player_cmd.append('--live')                                 # Avoid sync issues with long playing streams

            if CONFIG.AUDIO_MODE == AUDIOMODE.FULLSCREEN and \
                    self.visible and self.fullscreen_mode and stream.has_audio:
                # OMXplayer can only open 8 instances instead of 16 when audio is enabled,
                # this can also lead to total system lockups...
                # Work around this by disabling the audio stream when in windowed mode,
                # in fullscreen mode, we can safely enable audio again.
                # set_visible() and set_invisible() methods are also adopted for this.

                # Volume % to millibels conversion
                volume = int(2000 * math.log10(max(CONFIG.AUDIO_VOLUME, 0.001) / 100))
                player_cmd.extend(['--vol', str(volume)])                   # Set audio volume

                self._omx_audio_enabled = True
            else:
                player_cmd.extend(['--aidx', '-1'])                         # Disable audio stream
                self._omx_audio_enabled = False

            # Show our channel name with a custom subtitle file?
            # OMXplayer OSD not supported on pi4 hardware
            if sub_file and not "4B" in GLOBALS.PI_MODEL:
                if os.path.isfile(sub_file):
                    player_cmd.extend(['--subtitles', sub_file ])           # Add channel name as subtitle
                    player_cmd.extend(
                        ['--no-ghost-box', '--align', 'center',
                         '--lines', '1'])                                   # Set subtitle properties

        # VLC media player can play only in fullscreen mode
        # One fullscreen instance per display
        elif self.fullscreen_mode and stream.valid_video_fullscreen:
            self._player = PLAYER.VLCPLAYER

            player_cmd = ['cvlc',
                '--fullscreen',                                             # VLC does not support windowed mode without X11
                '--network-caching=' + str(CONFIG.BUFFERTIME_MS),           # Threshold of buffer in miliseconds
                '--no-keyboard-events',                                     # No keyboard events
                '--mmal-display=hdmi-' + str(self._display_num),            # Select the correct display
                '--mmal-layer=0',                                           # OMXplayer uses layers starting from 0, don't interference
                '--input-timeshift-granularity=0',                          # Disable timeshift feature
                '--vout=mmal_vout',                                         # Force MMAL mode
                '--gain=1',                                                 # Audio gain
                '--no-video-title-show'                                     # Disable filename popup on start
            ]

            if not self.force_udp and not stream.force_udp:
                player_cmd.append('--rtsp-tcp')                             # Force RTSP over TCP

            # Keep in mind that VLC instances can be reused for
            # other windows with possibly other audio settings!
            # So don't disable the audio output to quickly!
            if CONFIG.AUDIO_MODE == AUDIOMODE.FULLSCREEN:

                # VLC does not have a command line volume argument??
                pass

            else:
                player_cmd.append('--no-audio')                             # Disable audio stream

            if stream.url.startswith('file://'):
                player_cmd.append('--repeat')                               # Loop for local files (demo/test mode)

            # Show our channel name with a custom subtitle file?
            if sub_file and os.path.isfile(sub_file):
                player_cmd.extend(['--sub-file', sub_file])                 # Add channel name as subtitle

            # TODO: we need te reopen VLC every time for the correct sub?
            if ((sub_file and os.path.isfile(sub_file)) or Window._vlc_subs_enabled[self._display_num - 1]) and \
                    self.get_vlc_pid(self._display_num):

                LOG.WARNING(self._LOG_NAME, "closing already active VLC instance for display '%i' "
                                            "as subtitles (video OSD) are enabled" % self._display_num)

                player_pid = self.get_vlc_pid(self._display_num)

                utils.terminate_process(player_pid, force=True)
                self._pidpool_remove_pid(player_pid)
                Window.vlc_player_pid[self._display_num - 1] = 0

        else:
            LOG.ERROR(self._LOG_NAME, "stream '%s' with codec '%s' is not valid for playback" %
                      (stream.printable_url(), stream.codec_name))
            return

        # Check hardware video decoder impact
        if Window._total_weight + self.get_weight(stream) > CONSTANTS.HW_DEC_MAX_WEIGTH and CONFIG.HARDWARE_CHECK:
            LOG.ERROR(self._LOG_NAME, "current hardware decoder weight is '%i', max decoder weight is '%i'" %
                      (Window._total_weight, CONSTANTS.HW_DEC_MAX_WEIGTH))
            return
        else:
            Window._total_weight += self.get_weight(stream)

        # Set URL before stripping
        self.active_stream = stream
        url = stream.url

        if self._player == PLAYER.VLCPLAYER and self.get_vlc_pid(self._display_num):

            LOG.DEBUG(self._LOG_NAME, "reusing already active VLC instance for display '%i'" % self._display_num)

            if self.visible:
                # VLC player instance can be playing or in idle state.
                # Sending the play command will start fullscreen playback of our video/stream.
                # When VLC is playing other content, we will hijack it.

                # Enable/disable audio
                if CONFIG.AUDIO_MODE == AUDIOMODE.FULLSCREEN:
                    volume = CONFIG.AUDIO_VOLUME / 100
                    self._send_dbus_command(DBUS_COMMAND.PLAY_VOLUME, volume)

                # Start our stream
                self._send_dbus_command(DBUS_COMMAND.PLAY_PLAY)

                # Mark our steam as the active one for this display
                Window._vlc_active_stream_url[self._display_num - 1] = self.active_stream.url

            else:
                # Play command will be sent by 'stream_set_visible' later on.
                pass

            # Pretend like the player just started again
            self.playstate = PLAYSTATE.INIT2
            self._time_streamstart = time.monotonic()
            return

        else:

            LOG.DEBUG(self._LOG_NAME, "starting player with arguments '%s'" % player_cmd)
        
            # Add URL now, as we don't want sensitive credentials in the logfile...
            if self._player == PLAYER.OMXPLAYER:
                player_cmd.append(url)

            elif self._player == PLAYER.VLCPLAYER and self.visible:
                player_cmd.append(url)
                Window._vlc_active_stream_url[self._display_num - 1] = url

            if self._player == PLAYER.VLCPLAYER:
                # VLC changes its DBus string to 'org.mpris.MediaPlayer2.vlc.instancePID'
                # when opening a second instance, so we have to adjust it later on when we know the PID
                # Max number of VLC instances = number of displays = 2

                if self._pidpool_get_pid("--mmal-display=hdmi-"):
                    Window._vlc_dbus_ident[self._display_num - 1] = "org.mpris.MediaPlayer2.vlc.instance"
                else:
                    Window._vlc_dbus_ident[self._display_num - 1] = "org.mpris.MediaPlayer2.vlc"

                # Save the subtitle state for later use
                Window._vlc_subs_enabled[self._display_num - 1] = (sub_file and os.path.isfile(sub_file))

            subprocess.Popen(player_cmd, shell=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            if self._player == PLAYER.VLCPLAYER:
                # VLC does not have a command line argument for volume control??
                # As workaround, wait for VLC startup and send the desired volume with DBus
                time.sleep(0.5)
                self._send_dbus_command(DBUS_COMMAND.PLAY_VOLUME, CONFIG.AUDIO_VOLUME / 100, retries=5)

        self._time_streamstart = time.monotonic()
        self.playstate = PLAYSTATE.INIT1
        self._omx_duration = 0

    def player_initializing(self):
        """Check if the player is initializing, i.e. the player is not ready yet to accept DBus calls"""

        # Limit time consuming calls to 'get_stream_playstate()'
        if self.playstate == PLAYSTATE.INIT1:
            return self.get_stream_playstate() == PLAYSTATE.INIT1

        return False

    def player_buffering(self):
        """Check if the player is loading/buffering"""

        # Limit time consuming calls to 'get_stream_playstate()'
        if self.playstate == PLAYSTATE.INIT1 or self.playstate == PLAYSTATE.INIT2:
            return self.get_stream_playstate() == PLAYSTATE.INIT1 or self.get_stream_playstate() == PLAYSTATE.INIT2

        return False

    def get_omxplayer_pid(self):
        """Get OMXplayer instance PID for the requested display, 0 if not found"""

        return self._pidpool_get_pid(self._omx_dbus_ident)

    @classmethod
    def get_vlc_pid(cls, display_num):
        """Get VLC instance PID for the requested display, 0 if not found"""

        return cls._pidpool_get_pid("--mmal-display=hdmi-" + str(display_num))

    @classmethod
    def stop_all_players(cls, sigkill=False):
        """Stop all players the fast and hard way"""

        term_cmd = '-9' if sigkill else '-15'

        try:
            subprocess.Popen(
                ['killall', term_cmd, 'omxplayer.bin'],
                shell=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )

            subprocess.Popen(
                ['killall', term_cmd, 'vlc'],
                shell=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        except Exception as error:
            LOG.ERROR(cls._LOG_NAME, "stop_all_players pid kill error: %s" % str(error))

    # TODO: methods below are not thread safe

    @classmethod
    def _pidpool_get_pid(cls, player_identification):
        """Get Player PID from OS"""

        # PID already in PID pool
        for idx, cmdline in enumerate(cls._player_pid_pool_cmdline[1]):
            if player_identification in cmdline:
                return int(cls._player_pid_pool_cmdline[0][idx])

        # No? -> update PID pool
        cls.pidpool_update()

        for idx, cmdline in enumerate(cls._player_pid_pool_cmdline[1]):
            if player_identification in cmdline:
                return int(cls._player_pid_pool_cmdline[0][idx])

        return 0

    @classmethod
    def _pidpool_remove_pid(cls, pid):
        """Remove Player PID from pidpool"""

        for idx, _pid in enumerate(cls._player_pid_pool_cmdline[0]):

            if _pid == pid:
                LOG.DEBUG("PIDpool", "removed Player PID '%i' from pool" % pid)

                del cls._player_pid_pool_cmdline[0][idx]
                del cls._player_pid_pool_cmdline[1][idx]
                return True

        return False

    @classmethod
    def pidpool_update(cls):
        """Update the PID pool of OMXplayer and VLC media player instances"""

        cls._player_pid_pool_cmdline = [[], []]

        try:
            player_pids = subprocess.check_output(['pidof', 'vlc'],
                universal_newlines=True, timeout=5).split()

            LOG.DEBUG("PIDpool", "active VLCplayer PIDs '%s'" % player_pids)

            for player_pid in player_pids:
                cls._player_pid_pool_cmdline[0].append(int(player_pid))
                cls._player_pid_pool_cmdline[1].append(subprocess.check_output(
                    ['cat', str('/proc/%s/cmdline' % player_pid)], universal_newlines = True, timeout=5))

        except subprocess.CalledProcessError:
            pass

        try:
            player_pids = subprocess.check_output(['pidof', 'omxplayer.bin'],
                universal_newlines=True, timeout=5).split()

            LOG.DEBUG("PIDpool", "active OMXplayer PIDs '%s'" % player_pids)

            for player_pid in player_pids:
                cls._player_pid_pool_cmdline[0].append(int(player_pid))
                cls._player_pid_pool_cmdline[1].append(subprocess.check_output(
                    ['cat', str('/proc/%s/cmdline' % player_pid)], universal_newlines = True, timeout=5))

        except subprocess.CalledProcessError:
            pass
