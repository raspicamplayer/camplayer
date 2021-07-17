#!/usr/bin/python3

import time
import threading

import evdev
import queue


class InputMonitor(object):

    def __init__(self, event_type=['release', 'press', 'hold'], scan_interval=2500):
        self._devices = []
        self._event_queue = queue.Queue(maxsize=10)
        self._scan_interval = scan_interval / 1000
        self._event_up = True if 'release' in event_type else False
        self._event_down = True if 'press' in event_type else False
        self._event_hold = True if 'hold' in event_type else False
        self._running = True
        self._monitor_thread = threading.Thread(target=self._monitor, daemon=True).start()
        self._mouse_inhibit = time.monotonic()
        self._mouse_inhibit_duration = 0.5
        self._mouse_btn_state = 0
        self._mouse_abs_x = 500
        self._mouse_abs_y = 500
        
    def destroy(self):
        """Stop monitoring thread"""

        self._running = False

    def get_events(self):
        """Get queued keyboard events"""

        events = []
        while not self._event_queue.empty():
            event = self._event_queue.get_nowait()
            self._event_queue.task_done()
            events.append(event)
            
        return events

    def _scan_devices(self):
        """Scan for input devices"""

        return [evdev.InputDevice(path) for path in evdev.list_devices()]

    def _monitor(self):
        """Key monitoring thread"""

        last_scan_time = -self._scan_interval
        
        while self._running and threading.main_thread().is_alive():

            if time.monotonic() > last_scan_time + self._scan_interval:
                self._devices = self._scan_devices()
                last_scan_time = time.monotonic()

            # TODO fix
            # Somehow evdev misses button presses in its own loop
            # Looping faster than the expected time between button presses, hides this issue...
            # https://github.com/gvalkov/python-evdev/issues/101
            time.sleep(0.025)

            for device in self._devices:
                try:
                    while True:
                        event = device.read_one()
                        if event:
                            # keyboard and button events
                            if event.type == evdev.ecodes.EV_KEY:

                                # mouse buttons
                                if ( event.code in {evdev.ecodes.BTN_MOUSE,
                                                    evdev.ecodes.BTN_RIGHT,
                                                    evdev.ecodes.BTN_MIDDLE} ):
                                    # Left click: track (left) mouse button state
                                    # note that left mouse click by itself does not do anything
                                    if event.code == evdev.ecodes.BTN_MOUSE:
                                        self._mouse_btn_state = event.value
                                    # Right click, while left is already down, Quit program
                                    elif (      event.code == evdev.ecodes.BTN_RIGHT 
                                            and self._mouse_btn_state == 1
                                            and event.value == 0 ): 
                                        event.code = evdev.ecodes.KEY_Q
                                        self._event_queue.put_nowait(event)
                                    # Right click, while left is not already down, Pause autorotate
                                    elif (      event.code == evdev.ecodes.BTN_RIGHT
                                            and event.value == 0 ):
                                        event.code = evdev.ecodes.KEY_SPACE
                                        self._event_queue.put_nowait(event)

                                # other keys / keyboard keys
                                elif self._event_up and event.value == 0:
                                    self._event_queue.put_nowait(event)
                                elif self._event_down and event.value == 1:
                                    self._event_queue.put_nowait(event)
                                elif self._event_hold and event.value == 2:
                                    self._event_queue.put_nowait(event)

                            # mouse movement events
                            elif event.type == evdev.ecodes.EV_REL:

                                # unused for now, track absolute position
                                if event.code == evdev.ecodes.REL_X:
                                    self._mouse_abs_x += event.value;
                                    self._mouse_abs_x = min(1920, self._mouse_abs_x)
                                    self._mouse_abs_x = max(1, self._mouse_abs_x)
                                elif event.code == evdev.ecodes.REL_Y:
                                    self._mouse_abs_y += event.value;
                                    self._mouse_abs_y = min(1080, self._mouse_abs_y)
                                    self._mouse_abs_y = max(1, self._mouse_abs_y)

                                # Gestures, only one per timeslot.
                                if (time.monotonic() > self._mouse_inhibit + self._mouse_inhibit_duration):
                                    # wheel up/down is zoom in/out, iow, single/grid view
                                    if   (      event.code == evdev.ecodes.REL_WHEEL
                                            and abs(event.value) > 0 ):
                                        if event.value > 0: 
                                            event.code = evdev.ecodes.KEY_0
                                        else:
                                            event.code = evdev.ecodes.KEY_1
                                        self._mouse_inhibit = time.monotonic()
                                        self._event_queue.put_nowait(event)
                                    # move left/right while button down is prev/next screen
                                    elif (      event.code == evdev.ecodes.REL_X
                                            and self._mouse_btn_state == 1
                                            and abs(event.value) > 10 ):
                                        if event.value > 0:
                                            event.code = evdev.ecodes.KEY_RIGHT
                                        else:
                                            event.code = evdev.ecodes.KEY_LEFT
                                        self._mouse_inhibit = time.monotonic()
                                        self._event_queue.put_nowait(event)
                                    # move up/down while button down is higher/lower quality
                                    elif (      event.code == evdev.ecodes.REL_Y
                                            and self._mouse_btn_state == 1
                                            and abs(event.value) > 10 ):
                                        if event.value > 0:
                                            event.code = evdev.ecodes.KEY_DOWN
                                        else:
                                            event.code = evdev.ecodes.KEY_UP
                                        self._mouse_inhibit = time.monotonic()
                                        self._event_queue.put_nowait(event)

                            del event
                        else:
                            break
                except BlockingIOError:
                    pass
                except OSError:
                    pass
                except queue.Full:
                    pass

        for device in self._devices:
            try:
                device.close()
            except:
                pass
