#!/usr/bin/python3

import os
import sys
import signal
import time
import math

from enum import IntEnum, unique
from windowmanager import Window, PLAYSTATE
from utils.settings import CONFIG, LAYOUT, CHANGEOVER
from utils.constants import CONSTANTS
from utils.logger import LOG
from utils.globals import GLOBALS
from backgroundgen import BackGroundManager, BackGround


@unique
class StreamQuality(IntEnum):
    DEFAULT                 = 0     # Default or lower stream quality
    HIGHER                  = 1     # Higher than default stream quality
    HIGHEST                 = 2     # Highest stream quality

@unique
class Action(IntEnum):
    NONE                    = 0
    SWITCH_SINGLE           = 1
    SWITCH_GRID             = 2
    SWITCH_NEXT             = 3
    SWITCH_PREV             = 4
    SWITCH_QUALITY_UP       = 5
    SWITCH_QUALITY_DOWN     = 6
    SWITCH_PAUSE_UNPAUSE    = 7
    SWITCH_DISPLAY_CONTROL  = 8


class Screen(object):

    _LOG_NAME = "Screen"
    _IDX_NOT_SET = -1

    def __init__(self, layout, displaytime, screen_idx, display_idx):

        self.layout                     = layout                # Number of windows for this screen
        self.displaytime                = displaytime           # Screen active time when multiple screen configured
        self._weight                    = 0                     # Estimated performance impact for this screen
        self.grid_size                  = 0                     # Base grid size, usually 9 and/or 16 (3x3, 4x4)
        self.windows                    = []                    # Containing windows/video players
        self._screen_idx                = screen_idx            # Sequennce/index of this screen
        self._display_idx               = display_idx           # Display index this screen belongs to
        self._viewmode_single_win_idx   = self._IDX_NOT_SET     # Index of active/fullscreen window in single view mode
        self._viewmode_single           = False                 # Default mode is grid view mode
        self._viewmode_single_quality   = StreamQuality.DEFAULT # Preferred stream quality in single view mode

        # Initialize/buildup windows
        self._load_windows()

        # Parse window/stream mapping from config file
        self._parse_config()

        for window in self.windows:
            self._weight += window.get_weight()

        LOG.INFO(self._LOG_NAME, "init screen number '%i' with a total weight of '%i'" %
                 (self._screen_idx + 1, self._weight))

    def monitor_streams(self):
        """Monitor streams and attempt to fix broken ones"""

        broken_streams_detected = False

        for window in self.windows:
            if window.get_stream_playstate() == PLAYSTATE.BROKEN:
                LOG.WARNING(self._LOG_NAME, "restarting broken stream")
                window.stream_refresh()
                broken_streams_detected = True

        return broken_streams_detected

    def switch_quality_up(self):
        """Switch all windows to a higher quality stream"""

        if self._viewmode_single:

            # Higher quality stream available?
            stream = self.windows[self._viewmode_single_win_idx].stream_switch_quality_up(
                check_only=True, limit_default=False)

            if stream:

                # Don't stress HW too much, stop all other streams if quality > default
                if stream.quality > self.windows[self._viewmode_single_win_idx].\
                        get_default_stream(windowed=True).quality:

                    self._viewmode_single_quality = StreamQuality.HIGHER

                    for idx, window in enumerate(self.windows):
                        if idx != self._viewmode_single_win_idx:
                            window.stream_stop()

                # Higher quality stream available, switch now
                self.windows[self._viewmode_single_win_idx].stream_switch_quality_up(limit_default=False)

                if (self.windows[self._viewmode_single_win_idx].active_stream and
                        self.windows[self._viewmode_single_win_idx].active_stream.quality >=
                        self.windows[self._viewmode_single_win_idx].get_highest_quality_stream().quality):
                    self._viewmode_single_quality = StreamQuality.HIGHEST

        else:

            # Limit stream quality when in grid view mode with multiple windows
            for window in self.windows:
                window.stream_switch_quality_up(limit_default=len(self.windows) > 1)

    def switch_quality_down(self):
        """Switch all windows to a lower quality stream"""

        if self._viewmode_single:

            # Lower quality stream available?
            stream = self.windows[self._viewmode_single_win_idx].stream_switch_quality_down(check_only=True)

            if stream:

                # Lower quality stream available, switch now
                self.windows[self._viewmode_single_win_idx].stream_switch_quality_down()

                # Default or even a lower quality stream,
                # start all other windows again in background for faster prev/next switching
                if stream.quality <= \
                        self.windows[self._viewmode_single_win_idx].get_default_stream(windowed=True).quality:

                    for idx, window in enumerate(self.windows):
                        if idx != self._viewmode_single_win_idx and window.playstate == PLAYSTATE.NONE:
                            window.stream_start(visible=False, force_fullscreen=False)

                    self._viewmode_single_quality = StreamQuality.DEFAULT

        else:

            for window in self.windows:
                window.stream_switch_quality_down()

    def get_min_playtime(self):
        """Get the minimum playtime from the containing video players"""

        min_playtime = sys.maxsize

        for window in self.windows:
            if window.playstate != PLAYSTATE.NONE and window.playtime < min_playtime:
                min_playtime = window.playtime

        return min_playtime

    def get_max_playtime(self):
        """Get the maximum playtime from the containing video players"""

        max_playtime = 0

        for window in self.windows:
            if window.playstate != PLAYSTATE.NONE and window.playtime > max_playtime:
                max_playtime = window.playtime

        return max_playtime

    def switch_singleview(self, window_idx=0, next_window=False, prev_window=False):
        """
        Switch the requested window from grid to single view mode
        If already in single view mode, switch to next or previous window
        """

        if window_idx < 0 or window_idx >= len(self.windows) or len(self.windows) <= 1:
            return

        if (next_window or prev_window) and self._viewmode_single_win_idx:
            window_idx = self._viewmode_single_win_idx

        if next_window:

            # Find the first next valid window
            for _ in range(len(self.windows)):

                window_idx += 1
                if window_idx >= len(self.windows):
                    window_idx = 0

                # Just to check if there is at least one playable stream
                if self.windows[window_idx].get_lowest_quality_stream(windowed=False):
                    break

        elif prev_window:

            # Find the first previous valid window
            for _ in range(len(self.windows)):

                window_idx -= 1
                if window_idx < 0:
                    window_idx = len(self.windows) - 1

                # Just to check if there is at least one playable stream
                if self.windows[window_idx].get_lowest_quality_stream(windowed=False):
                    break

        # Already active, nothing to do
        if window_idx == self._viewmode_single_win_idx:
            return

        LOG.INFO(self._LOG_NAME, "switch window number '%i' to fullscreen" % (window_idx + 1))

        if self._viewmode_single_quality == StreamQuality.DEFAULT:

            # Making the requested window fullscreen first looks better than removing the
            # non needed windows off screen and then make the requested window fullscreen.
            # However I've seen GPU hangs?? when using this better looking option,
            # probably because it can lead to multiple active dispmanx layers at the same time.
            # Therefore don't use this method when we come from grid view mode (more active layers)
            if not self._viewmode_single:
                for idx, window in enumerate(self.windows):
                    if idx != window_idx:
                        window.stream_set_invisible(_async=True)

                # For now, assume 500ms is enough to hide our streams
                time.sleep(0.5)

            # Make requested window visible
            if self.windows[window_idx].playstate == PLAYSTATE.NONE:
                self.windows[window_idx].stream_start(visible=True, force_fullscreen=True) # This does select HQ?
            else:
                self.windows[window_idx].stream_set_visible(fullscreen=True)

            if self._viewmode_single:
                for idx, window in enumerate(self.windows):
                    if idx != window_idx:
                        window.stream_set_invisible()

        else:
            self.streams_stop()
            self.windows[window_idx].stream_start(
                visible=True, force_fullscreen=True, force_hq=self._viewmode_single_quality)

        self._viewmode_single_win_idx = window_idx
        self._viewmode_single = True

    def switch_gridview(self):
        """Switch the requested window from single (fullscreen) view to grid view mode"""

        if not self._viewmode_single:
            return

        LOG.INFO(self._LOG_NAME, "switching from single view to grid view mode")

        # The same comment about GPU crashes as described in "switch_singleview()" applies here.
        # So coming from single view mode, put our active window from fullscreen to windowed mode first
        # in order to limit overlapping dispmanx layers
        if self._viewmode_single:
            if self.windows[self._viewmode_single_win_idx].active_stream:
                if self.windows[self._viewmode_single_win_idx].active_stream.url == \
                        self.windows[self._viewmode_single_win_idx].get_default_stream(windowed=True).url:
                    self.windows[self._viewmode_single_win_idx].stream_set_visible(fullscreen=False)

        for idx, window in enumerate(self.windows):
            win_default_stream = window.get_default_stream(windowed=True)

            if window.active_stream:

                # Stop non default streams (possible HD) when switching back to grid view
                # Only default (lower quality SD) streams should be used in grid view,
                # this to avoid overloading the hardware decoder/scaler
                # Also for rare occasions where the stream is only playable in non windowed mode (VLC)
                if not win_default_stream or window.active_stream.url != win_default_stream.url:
                    window.stream_stop()

                # If already playing the default stream, set it visible
                else:
                    window.stream_set_visible(_async=True, fullscreen=False)

            else:
                window.stream_stop()

        time.sleep(0.25)
        self.streams_start(visible=True)

        self._viewmode_single_win_idx = self._IDX_NOT_SET
        self._viewmode_single = False
        self._viewmode_single_quality = StreamQuality.DEFAULT

    def streams_start(self, visible=False):
        """Start all containing windows/streams"""

        for window in self.windows:
            window.stream_start(visible=visible)

    def streams_stop(self):
        """Stop all containing windows/streams"""

        for window in self.windows:
            window.stream_stop()

    def streams_refresh(self):
        """Refresh all containing windows/streams"""

        for window in self.windows:
            window.stream_refresh()
            
    def streams_set_visible(self, gridindex=[]):
        """Set all or selected windows/streams visible"""
        
        for window in self.windows:
            if gridindex:
                for idx in gridindex:
                    if idx in window.gridindex:
                        window.stream_set_visible(_async=True)
                        break
            else:
                window.stream_set_visible(_async=True)
                
    def streams_set_invisible(self, gridindex=[]):
        """Set all or selected windows/streams invisible"""
        
        for window in self.windows:
            if gridindex:
                for idx in gridindex:
                    if idx in window.gridindex:
                        window.stream_set_invisible(_async=True)
                        break
            else:
                window.stream_set_invisible(_async=True)
            
    def get_weight(self, playing_only=False):
        """Get the total decoding weight for this screen"""

        weight = 0

        for window in self.windows:
            if not playing_only or window.playstate != PLAYSTATE.NONE:
                weight += window.get_weight()

        return weight

    def get_valid_windows(self):
        """Get the number of valid windows for this screen (= window with playable stream assigned)"""

        count = 0

        for window in self.windows:
            count += 1 if window.get_lowest_quality_stream() else 0

        return count

    def get_playing_windows(self):
        """Get the number of playing streams for this screen"""

        count = 0

        for window in self.windows:
            count += 0 if window.playstate == PLAYSTATE.NONE else 1

        return count

    def players_initializing(self):
        """All players ready to be (DBus) controlled?"""

        for window in self.windows:
            if window.player_initializing():
                return True
        return False

    def players_buffering(self):
        """All players done buffering?"""

        for window in self.windows:
            if window.player_buffering():
                return True
        return False
        
    def _load_windows(self):
        """Load windows based on the requested layout"""
        
        if self.layout == LAYOUT._1X1:
            nrows_ncolums = 1
            self.grid_size = [9, 16]
            
        elif self.layout == LAYOUT._2X2:
            nrows_ncolums = 2
            self.grid_size = [16]
            
        elif self.layout == LAYOUT._3X3:
            nrows_ncolums = 3
            self.grid_size = [9]
            
        elif self.layout == LAYOUT._4X4:
            nrows_ncolums = 4
            self.grid_size = [16]
    
        elif self.layout == LAYOUT._1P5:
            nrows_ncolums = 3
            self.grid_size = [9]
            
            # Add one larger window
            self.windows.append(Window(
                x1=CONSTANTS.VIRT_SCREEN_OFFSET_X,
                y1=CONSTANTS.VIRT_SCREEN_OFFSET_Y,
                x2=int(CONSTANTS.VIRT_SCREEN_OFFSET_X + (CONSTANTS.VIRT_SCREEN_WIDTH * 2) / 3),
                y2=int(CONSTANTS.VIRT_SCREEN_OFFSET_Y + (CONSTANTS.VIRT_SCREEN_HEIGHT * 2) / 3),
                gridindex=[0, 1, 3, 4], 
                screen_idx=self._screen_idx,
                window_idx=len(self.windows),
                display_idx=self._display_idx)
            )

        elif self.layout == LAYOUT._1P7:
            nrows_ncolums = 4
            self.grid_size = [16]

            # Add one larger window
            self.windows.append(Window(
                x1=CONSTANTS.VIRT_SCREEN_OFFSET_X,
                y1=CONSTANTS.VIRT_SCREEN_OFFSET_Y,
                x2=int(CONSTANTS.VIRT_SCREEN_OFFSET_X + (CONSTANTS.VIRT_SCREEN_WIDTH * 3) / 4),
                y2=int(CONSTANTS.VIRT_SCREEN_OFFSET_Y + (CONSTANTS.VIRT_SCREEN_HEIGHT * 3) / 4),
                gridindex=[0, 1, 2, 4, 5, 6, 8, 9, 10],
                screen_idx=self._screen_idx,
                window_idx=len(self.windows),
                display_idx=self._display_idx)
            )

        elif self.layout == LAYOUT._1P12:
            nrows_ncolums = 4
            self.grid_size = [16]
            
            # Add one larger window
            self.windows.append(Window(
                x1=CONSTANTS.VIRT_SCREEN_OFFSET_X,
                y1=CONSTANTS.VIRT_SCREEN_OFFSET_Y,
                x2=int(CONSTANTS.VIRT_SCREEN_OFFSET_X + (CONSTANTS.VIRT_SCREEN_WIDTH / 2)),
                y2=int(CONSTANTS.VIRT_SCREEN_OFFSET_Y + (CONSTANTS.VIRT_SCREEN_HEIGHT / 2)),
                gridindex=[0, 1, 4, 5], 
                screen_idx=self._screen_idx,
                window_idx=len(self.windows),
                display_idx=self._display_idx)
            )       
            
        elif self.layout == LAYOUT._2P8:
            nrows_ncolums = 4
            self.grid_size = [16]
            
            # Add 1st larger window
            self.windows.append(Window(
                x1=CONSTANTS.VIRT_SCREEN_OFFSET_X,
                y1=CONSTANTS.VIRT_SCREEN_OFFSET_Y,
                x2=int(CONSTANTS.VIRT_SCREEN_OFFSET_X + (CONSTANTS.VIRT_SCREEN_WIDTH / 2)),
                y2=int(CONSTANTS.VIRT_SCREEN_OFFSET_Y + (CONSTANTS.VIRT_SCREEN_HEIGHT / 2)),
                gridindex=[0, 1, 4, 5], 
                screen_idx=self._screen_idx,
                window_idx=len(self.windows),
                display_idx=self._display_idx)
            )
            
            # Add 2nd larger window
            self.windows.append(Window(
                x1=CONSTANTS.VIRT_SCREEN_OFFSET_X,
                y1=int(CONSTANTS.VIRT_SCREEN_OFFSET_Y + (CONSTANTS.VIRT_SCREEN_HEIGHT / 2)),
                x2=int(CONSTANTS.VIRT_SCREEN_OFFSET_X + (CONSTANTS.VIRT_SCREEN_WIDTH / 2)),
                y2=int(CONSTANTS.VIRT_SCREEN_OFFSET_Y + CONSTANTS.VIRT_SCREEN_HEIGHT),
                gridindex=[8, 9, 12, 13], 
                screen_idx=self._screen_idx,
                window_idx=len(self.windows),
                display_idx=self._display_idx)
            )     
            
        elif self.layout == LAYOUT._3P4:
            nrows_ncolums = 4
            self.grid_size = [16]
            
            # Add 1st larger window
            self.windows.append(Window(
                x1=CONSTANTS.VIRT_SCREEN_OFFSET_X,
                y1=CONSTANTS.VIRT_SCREEN_OFFSET_Y,
                x2=int(CONSTANTS.VIRT_SCREEN_OFFSET_X + (CONSTANTS.VIRT_SCREEN_WIDTH / 2)),
                y2=int(CONSTANTS.VIRT_SCREEN_OFFSET_Y + (CONSTANTS.VIRT_SCREEN_HEIGHT / 2)),
                gridindex=[0, 1, 4, 5], 
                screen_idx=self._screen_idx,
                window_idx=len(self.windows),
                display_idx=self._display_idx)
            )       
            
            # Add 2nd larger window
            self.windows.append(Window(
                x1=int(CONSTANTS.VIRT_SCREEN_OFFSET_X + (CONSTANTS.VIRT_SCREEN_WIDTH / 2)),
                y1=CONSTANTS.VIRT_SCREEN_OFFSET_Y,
                x2=int(CONSTANTS.VIRT_SCREEN_OFFSET_X + CONSTANTS.VIRT_SCREEN_WIDTH),
                y2=int(CONSTANTS.VIRT_SCREEN_OFFSET_Y + (CONSTANTS.VIRT_SCREEN_HEIGHT / 2)),
                gridindex=[2, 3, 6, 7],
                screen_idx=self._screen_idx,
                window_idx=len(self.windows),
                display_idx=self._display_idx)
            )

            # Add 3rd larger window
            self.windows.append(Window(
                x1=CONSTANTS.VIRT_SCREEN_OFFSET_X,
                y1=int(CONSTANTS.VIRT_SCREEN_OFFSET_Y + (CONSTANTS.VIRT_SCREEN_HEIGHT / 2)),
                x2=int(CONSTANTS.VIRT_SCREEN_OFFSET_X + (CONSTANTS.VIRT_SCREEN_WIDTH / 2)),
                y2=int(CONSTANTS.VIRT_SCREEN_OFFSET_Y + CONSTANTS.VIRT_SCREEN_HEIGHT),
                gridindex=[8, 9, 12, 13], 
                screen_idx=self._screen_idx,
                window_idx=len(self.windows),
                display_idx=self._display_idx)
            )

        else:
            LOG.ERROR(self._LOG_NAME, "layout configuration '%i' invalid, falling back on 1X1 layout" % self.layout)
            self.layout = LAYOUT._1X1
            nrows_ncolums = 1
            self.grid_size = [9, 16]
        
        win_height = CONSTANTS.VIRT_SCREEN_HEIGHT / nrows_ncolums
        win_width = CONSTANTS.VIRT_SCREEN_WIDTH/ nrows_ncolums
        
        top_left_y = 0
        bot_right_y = win_height
        
        for row in range(0, nrows_ncolums):
            top_left_x = 0
            bot_right_x = win_width
        
            for column in range(0, nrows_ncolums):
                if ((self.layout == LAYOUT._1P5 and (column > 1 or row > 1)) or
                        (self.layout == LAYOUT._1P7 and (column > 2 or row > 2)) or
                        (self.layout == LAYOUT._1P12 and (column > 1 or row > 1)) or
                        (self.layout == LAYOUT._2P8 and column > 1) or
                        (self.layout == LAYOUT._3P4 and (column > 1 and row > 1)) or
                        (self.layout == LAYOUT._1X1) or
                        (self.layout == LAYOUT._2X2) or
                        (self.layout == LAYOUT._3X3) or
                        (self.layout == LAYOUT._4X4)):
                    
                    gridindex = []
                    
                    # Find out which base grid indices are covered by this window
                    max_columns = int(math.sqrt(max(self.grid_size)))
                    div = int(max_columns / nrows_ncolums)
                    start_idx = (max_columns * div * row) + (div * column)
                    for _ in range(0, div):
                        for idx in range(start_idx, start_idx + div):
                            gridindex.append(idx)
                        start_idx = start_idx + max_columns
                    
                    # Add all other windows
                    self.windows.append(Window(
                        x1=CONSTANTS.VIRT_SCREEN_OFFSET_X + top_left_x,
                        y1=CONSTANTS.VIRT_SCREEN_OFFSET_Y + top_left_y,
                        x2=CONSTANTS.VIRT_SCREEN_OFFSET_X + bot_right_x,
                        y2=CONSTANTS.VIRT_SCREEN_OFFSET_Y + bot_right_y,
                        gridindex=gridindex,
                        screen_idx=self._screen_idx,
                        window_idx=len(self.windows),
                        display_idx=self._display_idx)
                    )

                top_left_x = top_left_x + win_width
                bot_right_x = bot_right_x + win_width

            bot_right_y = bot_right_y + win_height
            top_left_y = top_left_y + win_height
        
    def _parse_config(self):
        """Parse window settings and stream mapping from config file"""

        # Parse the device, channel and stream mapping from config
        for idx in range(0, len(self.windows)):

            # Add window stream URL
            # If parsing fails, just continue with the next window
            try:
                if CONFIG.has_setting(str("SCREEN%i" % (self._screen_idx + 1)), str("window%i" % (idx + 1))):

                    window_map = CONFIG.read_setting(str("SCREEN%i" % (self._screen_idx + 1)),
                                                     str("window%i" % (idx + 1))).split(',')

                    if len(window_map) == 2:
                        if CONFIG.has_section(window_map[0].upper()):

                            # When the main and subchannel are defined -> e.g. "channel1.1_url"
                            if CONFIG.has_setting(window_map[0].upper(), window_map[1]):
                                self.windows[idx].add_stream(CONFIG.read_setting(window_map[0].upper(), window_map[1]))

                            # Only main channel defined, add all matching subchannels -> "channel1_url"
                            # This is the preferred method as it allows us to switch between subchannels
                            # depending on settings, stream quality, available bandwidth, ...
                            else:
                                for setting, value in CONFIG.get_settings_for_section(window_map[0].upper()):
                                    if window_map[1].split("_")[0] in setting and "url" in setting:
                                        self.windows[idx].add_stream(value)

                            if '_' in window_map[1]:
                                channel_setting_base = window_map[1].split('_')[0]  # Format: channel1_url
                            else:
                                channel_setting_base = window_map[1].split(".")[0]  # Format: channel1.1_url

                            # Channel name defined?
                            channel_name_set = channel_setting_base + "_name"
                            if CONFIG.has_setting(window_map[0].upper(), channel_name_set):
                                self.windows[idx].set_display_name(
                                    CONFIG.read_setting(window_map[0].upper(), channel_name_set))

                            # Force UDP enabled?
                            force_udp_set = channel_setting_base + "_force_udp"
                            if CONFIG.has_setting(window_map[0].upper(), force_udp_set):
                                self.windows[idx].force_udp = CONFIG.read_setting_default_int(
                                    window_map[0].upper(), force_udp_set, 0)

            except Exception as ex:
                LOG.ERROR(self._LOG_NAME, "configfile parsing error: %s" % str(ex))


class ScreenManager(object):

    _MODULE = "ScreenManager"
    _IDX_NOT_SET = -1

    def __init__(self):
        self._active_screen_idx         = [self._IDX_NOT_SET    for _ in range(GLOBALS.NUM_DISPLAYS)]   # Screen index of currently active screen
        self._next_active_screen_idx    = [self._IDX_NOT_SET    for _ in range(GLOBALS.NUM_DISPLAYS)]   # Screen index of next active screen (=screen rotation pending/pre-buffering)
        self._prev_screen_idx           = [self._IDX_NOT_SET    for _ in range(GLOBALS.NUM_DISPLAYS)]   # Screen index of previous active screen
        self._screens                   = [[]                   for _ in range(GLOBALS.NUM_DISPLAYS)]   # Assigned screens
        self._timer_last_screenchange   = [0                    for _ in range(GLOBALS.NUM_DISPLAYS)]   # Timestamp of last screen rotation
        self._timer_last_watchdog       = [0                    for _ in range(GLOBALS.NUM_DISPLAYS)]   # Timestamp of last stream/player check (watchdog)
        self._single_window_mode        = [False                for _ in range(GLOBALS.NUM_DISPLAYS)]   # Force single view mode (False = grid mode)
        self._paused                    = [False                for _ in range(GLOBALS.NUM_DISPLAYS)]   # Pause automatic screen rotation
        self._timer_hide_icon           = [0                    for _ in range(GLOBALS.NUM_DISPLAYS)]   # Timestamp of icon overlay timeout
        self._pending_action            = [Action.NONE, None]                                           # Pending user triggered action [action, parameter]
        self._selected_display          = 0                                                             # Index of display to control with keyboard/remote

        # Parse screen configuration from file
        self._parse_config()

    @property
    def valid_screens(self):
        """Get valid screens count"""

        count = 0

        for i in range(GLOBALS.NUM_DISPLAYS):
            count += len(self._screens[i])

        return count

    def on_action(self, action, param=None):
        """Set action to be executed"""

        if self._pending_action and self._pending_action[0] != Action.NONE:
            LOG.WARNING(self._MODULE, "ignoring action '%s', still processing action '%s'"
                        % (action, self._pending_action[0]))
            return

        self._pending_action = [action, param]

    def _get_next_idx(self, display_idx=0):
        """Get next screen index"""

        display_idx = 1 if display_idx == 1 else 0

        if self._active_screen_idx[display_idx] == self._IDX_NOT_SET:
            return 0
            
        idx = self._active_screen_idx[display_idx] + 1
        if idx >= len(self._screens[display_idx]):
            idx = 0
            
        return idx

    def _get_prev_idx(self, display_idx=0):
        """Get previous screen index"""

        display_idx = 1 if display_idx == 1 else 0

        if self._active_screen_idx[display_idx] == self._IDX_NOT_SET:
            return 0
            
        idx = self._active_screen_idx[display_idx] - 1
        if idx < 0:
            idx = len(self._screens[display_idx]) - 1
            
        return idx
    
    def start_screen(self, screen_idx, display_idx=0, visible=True):
        """Start windows for screen and set indices correct"""

        display_idx = 1 if display_idx == 1 else 0

        if screen_idx >= len(self._screens[display_idx]):
            return

        LOG.DEBUG(self._MODULE, "starting all streams for screen '%i' on display '%i'"
                  % (screen_idx + 1, display_idx + 1))
            
        if visible:
            BackGroundManager.show_background(
                BackGround.NOLINK(self._screens[display_idx][screen_idx].layout), display_idx=display_idx)

            self._prev_screen_idx[display_idx] = self._active_screen_idx[display_idx]
            self._active_screen_idx[display_idx] = screen_idx
            self._screens[display_idx][screen_idx].streams_start(visible=True)
            self._timer_last_screenchange[display_idx] = time.monotonic()
            self._next_active_screen_idx[display_idx] = self._IDX_NOT_SET
        else:
            self._next_active_screen_idx[display_idx] = screen_idx
            self._screens[display_idx][screen_idx].streams_start(visible=False)

    def stop_screen(self, screen_idx=_IDX_NOT_SET, display_idx=_IDX_NOT_SET):
        """Stop all containing windows"""

        LOG.DEBUG(self._MODULE, "stopping all streams for screen number '%i'" % (screen_idx + 1))

        display_idx = 1 if display_idx == 1 else 0

        # No screen index given, stop all screens
        if screen_idx == self._IDX_NOT_SET:

            # TODO: is this even in use?

            # No display index given, stop all screens on all displays
            if display_idx == self._IDX_NOT_SET:

                for disp_idx in range(GLOBALS.NUM_DISPLAYS):
                    for screen in self._screens[disp_idx]:
                        screen.streams_stop()

                # Just to be sure there are no leftovers/freezed players
                Window.stop_all_players(sigkill=True)

                for disp_idx in range(GLOBALS.NUM_DISPLAYS):
                    self._next_active_screen_idx[disp_idx] = self._IDX_NOT_SET

            # Only stop screens on given display
            else:
                for screen in self._screens[display_idx]:
                    screen.streams_stop()

                self._next_active_screen_idx[display_idx] = self._IDX_NOT_SET

        # Only stop given screen on given display
        elif display_idx != self._IDX_NOT_SET:
            self._screens[display_idx][screen_idx].streams_stop()

            if screen_idx == self._next_active_screen_idx[display_idx]:
                self._next_active_screen_idx[display_idx] = self._IDX_NOT_SET

    def refresh_screen(self, screen_idx=_IDX_NOT_SET, display_idx=0):
        """Refresh all containing windows"""

        if screen_idx == self._IDX_NOT_SET:
            return

        self._screens[display_idx][screen_idx].streams_refresh()

    def _execute_pending_action(self):
        """Execute pending user based actions"""
        
        if (not self._pending_action) or self._pending_action[0] == Action.NONE:
            return

        action = self._pending_action[0]
        param = self._pending_action[1]

        LOG.INFO(self._MODULE, "executing user action '%s'" % str(action))
        
        # Reset timer to prevent screen rotation kicking in
        self._timer_last_screenchange[self._selected_display] = time.monotonic()

        # Switch to grid view
        if action == Action.SWITCH_GRID:
            self._action_switch_grid()

        # Switch to single view
        elif action == Action.SWITCH_SINGLE:
            self._action_switch_single(window_idx=param)

        # Switch to previous/next window/screen
        elif action == Action.SWITCH_NEXT or action == Action.SWITCH_PREV:
            if self._single_window_mode[self._selected_display]:
                self._action_switch_single(
                    next_window=action == Action.SWITCH_NEXT, prev_window=action == Action.SWITCH_PREV)
            else:
                self._action_switch_prev_next(action)

        # Switch to higher/lower quality stream
        elif action == Action.SWITCH_QUALITY_UP or action == Action.SWITCH_QUALITY_DOWN:
            self._action_switch_quality(action)

        elif action == Action.SWITCH_PAUSE_UNPAUSE:
            self._paused[self._selected_display] = not self._paused[self._selected_display]

        elif action == Action.SWITCH_DISPLAY_CONTROL:

            # Hide the control icon on the current display
            self._timer_hide_icon[self._selected_display] = time.monotonic()

            self._selected_display += 1
            if self._selected_display >= GLOBALS.NUM_DISPLAYS:
                self._selected_display = 0

            BackGroundManager.show_icon(BackGround.CONTROL, display_idx=self._selected_display)

            # Show the control icon on the new display for 5 seconds
            self._timer_hide_icon[self._selected_display] = time.monotonic() + 5

        self._pending_action = [Action.NONE, None]

    def _action_switch_quality(self, action):
        """Action: switch quality of stream up/down"""

        display_idx = self._selected_display

        self._paused[display_idx] = True

        BackGroundManager.show_icon(BackGround.LOADING, display_idx=display_idx)

        active_screen_idx = self._active_screen_idx[display_idx]
        active_screen = self._screens[display_idx][active_screen_idx]

        if action == Action.SWITCH_QUALITY_UP:
            active_screen.switch_quality_up()
        elif action == Action.SWITCH_QUALITY_DOWN:
            active_screen.switch_quality_down()

    def _action_switch_grid(self):
        """Action: switch from single to grid view mode"""

        display_idx = self._selected_display

        self._paused[display_idx] = False
        self._single_window_mode[self._selected_display] = False

        BackGroundManager.show_icon(BackGround.LOADING, display_idx=display_idx)

        BackGroundManager.show_background(
            BackGround.NOLINK(self._screens[display_idx][self._active_screen_idx[display_idx]].layout),
            display_idx=display_idx)

        self._screens[display_idx][self._active_screen_idx[display_idx]].switch_gridview()

    def _action_switch_single(self, window_idx=0, next_window=False, prev_window=False):
        """Action: switch to single view mode (i.e. resize one window to fullscreen dimensions)"""

        display_idx = self._selected_display

        self._paused[display_idx] = True

        # Single view mode is already on if the screen only has one window
        if len(self._screens[display_idx][self._active_screen_idx[display_idx]].windows) <= 1:
            return

        self._single_window_mode[self._selected_display] = True

        BackGroundManager.show_icon(BackGround.LOADING, display_idx=display_idx)

        self._screens[display_idx][self._active_screen_idx[display_idx]].switch_singleview(
            window_idx=window_idx, next_window=next_window, prev_window=prev_window)

        BackGroundManager.show_background(BackGround.NOLINK(1), display_idx=display_idx)

    def _action_switch_prev_next(self, action):
        """Action: switch to previous or next screen"""

        display_idx = self._selected_display

        new_screen_idx = self._get_next_idx(display_idx=display_idx) \
            if action == Action.SWITCH_NEXT else self._get_prev_idx(display_idx=display_idx)

        # Pause screen rotation
        self._paused[display_idx] = True

        BackGroundManager.show_icon(BackGround.LOADING, display_idx=display_idx)

        # Stop all screens for this display
        self.stop_screen(display_idx=self._selected_display)
        time.sleep(0.5)

        # To be sure no hanging player instances are left
        # The prev/next action actually acts as a hard refresh function
        if GLOBALS.NUM_DISPLAYS <= 1:
            Window.stop_all_players(sigkill=True)

        BackGroundManager.show_background(BackGround.NOLINK(
            self._screens[self._selected_display][new_screen_idx].layout), display_idx=display_idx)

        # Start new screen
        self.start_screen(screen_idx=new_screen_idx, display_idx=self._selected_display)

    def _monitor_players(self):
        """
        Checks for misbehaving player instances and broken streams
        TODO: Can we find a better location for this?
        """

        # Be sure all players are initialized otherwise
        # we might kill them later on
        for display_idx in range(GLOBALS.NUM_DISPLAYS):
            for screen in self._screens[display_idx]:
                if screen.players_initializing():
                    return

        LOG.DEBUG(self._MODULE, "player watchdog")

        # (Re)Fetch PIDs from the OS
        Window.pidpool_update()

        for PID in Window._player_pid_pool_cmdline[0]:

            pid_found = False

            for display_idx in range(GLOBALS.NUM_DISPLAYS):
                if len(self._screens[display_idx]) <= 0:
                    continue

                screens = self._screens[display_idx]
                screen_idx = self._active_screen_idx[display_idx]
                next_active_screen_idx = self._next_active_screen_idx[display_idx]

                # Does this PID belongs to our active screen?
                for window in screens[screen_idx].windows:
                    if window.omx_player_pid == int(PID) and window.playstate != PLAYSTATE.NONE:
                        pid_found = True
                        break

                # PID not found, maybe it belongs to the next active screen (pre-buffering already in background)
                if not pid_found and next_active_screen_idx != self._IDX_NOT_SET:
                    for window in screens[next_active_screen_idx].windows:
                        if window.omx_player_pid == int(PID) and window.playstate != PLAYSTATE.NONE:
                            pid_found = True
                            break

                # PID not found, does it belongs to idling VLC media player instances?
                if not pid_found:
                    for vlc_pid in Window.vlc_player_pid:
                        if vlc_pid == int(PID):
                            pid_found = True
                            break

            if not pid_found:
                LOG.ERROR(self._MODULE, "inactive player PID found (%s), "
                    "this should not happen, sending SIGKILL" % int(PID))

                os.kill(int(PID), signal.SIGKILL)
                Window._pidpool_remove_pid(int(PID))
   
    def _screen_rotate_next_active(self, display_idx=0):
        """
        Switchover from the current screen to the next active one
        Assumes the next screen is already pre-buffering/playing in the background
        """

        if self._next_active_screen_idx[display_idx] == self._IDX_NOT_SET:
            LOG.ERROR(self._MODULE, "cannot rotate screen, no next active screen set")
            return
        
        self._prev_screen_idx[display_idx] = self._active_screen_idx[display_idx]
        self._active_screen_idx[display_idx] = self._next_active_screen_idx[display_idx]
        
        LOG.DEBUG(self._MODULE, "switch over from screen '%i' to '%i'"
                  % (self._prev_screen_idx[display_idx] + 1, self._active_screen_idx[display_idx] + 1))

        old_grid = self._screens[display_idx][self._prev_screen_idx[display_idx]].grid_size
        new_grid = self._screens[display_idx][self._active_screen_idx[display_idx]].grid_size
        grid_match = False

        for grid_s in new_grid:
            if grid_s in old_grid:
                grid_match = True
                break

        if not grid_match:
            # Windows do not visually match when switching from a 4x4 grid to a 3x3 grid and reverse.
            # In this case it is better to set all windows invisible, show background and set all new windows visible.

            LOG.WARNING(self._MODULE, "gridsizes do not match for a smooth changeover, "
                                    "old grid '%s' new grid '%s'" % (str(old_grid), str(new_grid)))

            self._screens[display_idx][self._prev_screen_idx[display_idx]].streams_set_invisible()

            BackGroundManager.show_background(BackGround.NOLINK(
                self._screens[display_idx][self._active_screen_idx[display_idx]].layout), display_idx=display_idx)

            time.sleep(0.25)
            self._screens[display_idx][self._active_screen_idx[display_idx]].streams_set_visible()

        else:

            BackGroundManager.show_background(BackGround.NOLINK(
                self._screens[display_idx][self._active_screen_idx[display_idx]].layout), display_idx=display_idx)

            for i in range(0, len(self._screens[display_idx][self._prev_screen_idx[display_idx]].windows)):

                if self._prev_screen_idx != self._active_screen_idx:

                    old_grid_idx = self._screens[display_idx][self._prev_screen_idx[display_idx]].windows[i].gridindex
                    changeover_idx = old_grid_idx[:]

                    # In case the new window covers more grid positions, we want to add them too
                    # For example switching from a 3X3 to 1X1 grid view
                    for y in range (0, len(self._screens[display_idx][self._active_screen_idx[display_idx]].windows)):
                        new_grid_idx = self._screens[display_idx][self._active_screen_idx[display_idx]].windows[y].gridindex
                        for old_idx in old_grid_idx:
                            if old_idx in new_grid_idx:
                                for new_idx in new_grid_idx:
                                    if new_idx not in changeover_idx:
                                        changeover_idx.append(new_idx)

                    LOG.DEBUG(self._MODULE, "set windows with indices '%s' visible" % str(changeover_idx))

                    # Do the actual switchover
                    # Smooth is harder for the hvs (hardware video scaler)
                    if CONFIG.CHANGE_OVER == CHANGEOVER.PREBUFFER_SMOOTH:
                        self._screens[display_idx][self._active_screen_idx[display_idx]].\
                            streams_set_visible(changeover_idx)

                        # 500ms especially needed for VLC startup without a black screen interval
                        time.sleep(0.5)

                        self._screens[display_idx][self._prev_screen_idx[display_idx]].\
                            streams_set_invisible(changeover_idx)
                    else:
                        self._screens[display_idx][self._prev_screen_idx[display_idx]].\
                            streams_set_invisible(changeover_idx)

                        time.sleep(0.05)

                        self._screens[display_idx][self._active_screen_idx[display_idx]].\
                            streams_set_visible(changeover_idx)

            # Set the remaining windows visible, if any
            self._screens[display_idx][self._active_screen_idx[display_idx]].streams_set_visible()
        
        if self._timer_last_screenchange[display_idx] > 0:
            LOG.DEBUG(self._MODULE, "screen '%i' was active for '%i' milliseconds" % (
                self._prev_screen_idx[display_idx] + 1,
                (time.monotonic() - self._timer_last_screenchange[display_idx]) * 1000))

        self._timer_last_screenchange[display_idx] = time.monotonic()
        self._next_active_screen_idx[display_idx] = self._IDX_NOT_SET

    def do_work(self):
        """Worker loop for screen handling"""

        # Handle the very first start on each display
        for display_idx in range(GLOBALS.NUM_DISPLAYS):
            if self._active_screen_idx[display_idx] == self._IDX_NOT_SET and len(self._screens[display_idx]) > 0:
                self.start_screen(screen_idx=0, visible=True, display_idx=display_idx)
                return

        # Be sure all players are initialized otherwise
        # we might not be able to stop/move windows later on
        for display_idx in range(GLOBALS.NUM_DISPLAYS):
            for screen in self._screens[display_idx]:
                if screen.players_initializing():
                    return

        # User action pending? e.g. switch screen, switch stream quality, etc.
        if self._pending_action and self._pending_action[0] != Action.NONE:
            self._execute_pending_action()
            return

        for display_idx in range(GLOBALS.NUM_DISPLAYS):

            if self._active_screen_idx[display_idx] == self._IDX_NOT_SET:
                continue

            # Default_pause = don't automatically rotate screens
            #   When    1: Displaytime of screen is set to '0'
            #           2: Only one screen is configured
            default_paused = self._screens[display_idx][self._active_screen_idx[display_idx]].displaytime == 0 or \
                len(self._screens[display_idx]) <= 1

            # The user can also pause/unpause screen rotation
            rotation_paused = default_paused or self._paused[display_idx]

            # Remove 'LOADING' overlay if all players are playing
            if BackGroundManager.active_icon[display_idx] == BackGround.LOADING:
                if not self._screens[display_idx][self._active_screen_idx[display_idx]].players_buffering():
                    BackGroundManager.hide_icon(display_idx=display_idx)

            # Remove 'PAUSED' overlay if not paused anymore
            elif BackGroundManager.active_icon[display_idx] == BackGround.PAUSED:
                if not self._paused[display_idx]:
                    BackGroundManager.hide_icon(display_idx=display_idx)

            # Remove timed overlays when timer expired
            elif self._timer_hide_icon[display_idx] and time.monotonic() > self._timer_hide_icon[display_idx]:
                BackGroundManager.hide_icon(display_idx=display_idx)
                self._timer_hide_icon[display_idx] = 0

            # Add 'PAUSED' overlay if paused and no other icon is active
            if rotation_paused and not default_paused and not BackGroundManager.active_icon[display_idx]:
                BackGroundManager.show_icon(BackGround.PAUSED, display_idx=display_idx)

            if rotation_paused:

                # In case the next screen was pre-buffering while screen rotation was paused
                if (self._next_active_screen_idx[display_idx] != self._IDX_NOT_SET and
                        self._next_active_screen_idx[display_idx] != self._active_screen_idx):

                    LOG.WARNING(self._MODULE,
                        "screenrotation paused while pre-buffering, stopping screen with index '%i'"
                        % self._next_active_screen_idx[display_idx])

                    self.stop_screen(screen_idx=self._next_active_screen_idx[display_idx], display_idx=display_idx)
                    self._next_active_screen_idx[display_idx] = self._IDX_NOT_SET

            else:

                cur_playing = 0
                req_playing = 0
                cur_weight = 0
                req_weight = 0
                force_non_smooth_rotation = False

                next_active_screen_idx = self._get_next_idx(display_idx=display_idx)
                req_playing = self._screens[display_idx][next_active_screen_idx].get_valid_windows()
                req_weight = self._screens[display_idx][next_active_screen_idx].get_weight(playing_only=False)

                for dis_idx in range(GLOBALS.NUM_DISPLAYS):
                    for screen in self._screens[dis_idx]:
                        cur_playing += screen.get_playing_windows()
                        cur_weight += screen.get_weight(playing_only=True)

                # The hardware can only handle a limited amount of decoders/players
                if cur_playing + req_playing > CONSTANTS.MAX_DECODER_STREAMS and cur_playing > 0:
                    force_non_smooth_rotation = True

                # The hardware can only decode a limited amount of pixels per second
                elif cur_weight + req_weight > CONSTANTS.HW_DEC_MAX_WEIGTH and cur_weight > 0 and CONFIG.HARDWARE_CHECK:
                    force_non_smooth_rotation = True

                # Can we handle a new smooth screen-rotation?
                if force_non_smooth_rotation and \
                        self._next_active_screen_idx[display_idx] == self._IDX_NOT_SET or \
                        CONFIG.CHANGE_OVER == CHANGEOVER.NORMAL:

                    if time.monotonic() > self._timer_last_screenchange[display_idx] + \
                            self._screens[display_idx][self._active_screen_idx[display_idx]].displaytime:

                        if force_non_smooth_rotation:
                            LOG.WARNING(self._MODULE,
                                        "Forcing non-smooth screen-rotation for display '%i', "
                                        "active weight before switchover '%i', "
                                        "active players count before switchover '%i'"
                                        % (display_idx + 1, cur_weight, cur_playing))
                        else:
                            LOG.INFO(self._MODULE, "non-smooth screen-rotation for display '%i'" % (display_idx + 1))

                        BackGroundManager.show_icon(BackGround.LOADING, display_idx=display_idx)

                        self.stop_screen(screen_idx=self._active_screen_idx[display_idx], display_idx=display_idx)

                        if self._next_active_screen_idx[display_idx] != next_active_screen_idx:
                            self.start_screen(screen_idx=next_active_screen_idx, visible=True, display_idx=display_idx)
                            return

                else:

                    # Time to start pre-buffering the next active window?
                    if time.monotonic() > self._timer_last_screenchange[display_idx] + \
                            self._screens[display_idx][self._active_screen_idx[display_idx]].displaytime - \
                            CONFIG.PLAYTIMEOUT_SEC:

                        next_active_screen_idx = self._get_next_idx(display_idx=display_idx)

                        if self._next_active_screen_idx[display_idx] != next_active_screen_idx:
                            self.start_screen(screen_idx=next_active_screen_idx, visible=False, display_idx=display_idx)
                            return

                    # Next active screen pre-buffering in background?
                    if self._next_active_screen_idx[display_idx] != self._IDX_NOT_SET and \
                            self._next_active_screen_idx[display_idx] != self._active_screen_idx[display_idx]:

                        # Time to switchover to the next active screen?
                        if (time.monotonic() > (self._timer_last_screenchange[display_idx] +
                                self._screens[display_idx][self._active_screen_idx[display_idx]].displaytime)):

                            # Make new screen active
                            self._screen_rotate_next_active(display_idx=display_idx)

                            # Stop all streams from the old screen
                            self.stop_screen(screen_idx=self._prev_screen_idx[display_idx], display_idx=display_idx)
                            return

            # Refresh complete screen if configured so
            if CONFIG.REFRESHTIME_MINUTES and rotation_paused:
                if self._screens[display_idx][self._active_screen_idx[display_idx]].get_max_playtime() > \
                        CONFIG.REFRESHTIME_MINUTES * 60:

                    LOG.INFO(self._MODULE, "refreshing screen as defined in configuration")

                    BackGroundManager.show_icon(BackGround.LOADING, display_idx=display_idx)

                    self.refresh_screen(screen_idx=self._active_screen_idx[display_idx], display_idx=display_idx)
                    return

            # Stream watchdog attempts to restart broken streams
            if time.monotonic() > self._timer_last_watchdog[display_idx] + CONFIG.STREAM_WATCHDOG_SEC and \
                    (rotation_paused or time.monotonic() < self._timer_last_screenchange[display_idx] +
                     self._screens[display_idx][self._active_screen_idx[display_idx]].displaytime - 10):

                LOG.DEBUG(self._MODULE, "stream/player health checking for display number '%i'" % (display_idx + 1))

                # Monitor players = kill hanged/inactive instances
                self._monitor_players()

                # Monitor streams = restart broken streams
                self._screens[display_idx][self._active_screen_idx[display_idx]].monitor_streams()

                self._timer_last_watchdog[display_idx] = time.monotonic()
                return
        
    def _parse_config(self):
        """
        Parse screen settings from config file and buildup windows.
        A screen can consists out of multiple windows (grid layout),
        each window can contain multiple video streams (i.e. main and substream)
        """

        # Parse screen configuration
        for scrn_num in range(1, CONSTANTS.MAX_SCREENS + 1):

            if not CONFIG.has_section(str("SCREEN%i" % scrn_num)):
                continue
            
            layout       = CONFIG.read_setting_default_int(str("SCREEN%i" % scrn_num), "layout",        LAYOUT._1X1)
            displaytime  = CONFIG.read_setting_default_int(str("SCREEN%i" % scrn_num), "displaytime",   CONFIG.SHOWTIME)
            display_num  = CONFIG.read_setting_default_int(str("SCREEN%i" % scrn_num), "display",       1)  # 1 = Default HDMI port

            if display_num == 0:
                continue

            # Configuration swapped between single and dual display models?
            if display_num != 1 and GLOBALS.NUM_DISPLAYS <= 1 and CONFIG.HARDWARE_CHECK:
                LOG.WARNING(self._MODULE, "Configuration for multiple displays found, but hardware does "
                                          "only support one display. Forcing every screen to the first display...")
                display_num = 1
                
            # Initialize screen object and buildup windows
            screen = Screen(layout=layout, displaytime=displaytime, screen_idx=scrn_num-1, display_idx=display_num-1)

            LOG.INFO(self._MODULE, "added screen number '%i' to display '%i' with layout '%i' and displaytime '%i'" %
                     (scrn_num, display_num, layout, displaytime))

            self._screens[display_num - 1].append(screen)

            BackGroundManager.add_background(window_count=screen.layout, display_idx=display_num-1)

        # Add backgrounds and icons based on the parsed screen configuration
        for display_idx in range(GLOBALS.NUM_DISPLAYS):

            if len(self._screens[display_idx]) <= 0:
                continue

            # 1x1 always required as the user can 'zoom in' a window
            BackGroundManager.add_background(window_count=1, display_idx=display_idx)

            # Add some icons
            BackGroundManager.add_icon(BackGround.LOADING, display_idx=display_idx)
            BackGroundManager.add_icon(BackGround.PAUSED, display_idx=display_idx)
            BackGroundManager.add_icon(BackGround.CONTROL, display_idx=display_idx)

        BackGroundManager.load_backgrounds()
        BackGroundManager.load_icons()
