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
                            if event.type == evdev.ecodes.EV_KEY:
                                if self._event_up and event.value == 0:
                                    self._event_queue.put_nowait(event)
                                elif self._event_down and event.value == 1:
                                    self._event_queue.put_nowait(event)
                                elif self._event_hold and event.value == 2:
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
