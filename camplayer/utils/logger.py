#!/usr/bin/python3

import datetime
from enum import IntEnum
from enum import unique

from .settings import CONFIG
from .constants import CONSTANTS


@unique
class LOGLEVEL(IntEnum):
    DEBUG   = 0
    INFO    = 1
    WARNING = 2
    ERROR   = 3


def _split_message(message):
    """Split log message in multiple lines if exceeding MAX_LINE_LEN"""
    
    if len(message) <= CONSTANTS.LOG_LINE_LEN:
        return [message]
        
    response = []
    for i in range(0, len(message), CONSTANTS.LOG_LINE_LEN):
        response.append(message[i: (i + CONSTANTS.LOG_LINE_LEN)])
        
    return response


def _output_message(prefix, message):
    """Print log message to console"""
    
    lines = _split_message(message)
    for idx, line in enumerate(lines):
        if idx == 0:
            print("%s - %s" % (prefix, line))
        else:
            print("%s --> %s" % (prefix, line))


def log_message(module, loglevel, message):
    """Format log message with log level and timestamp"""
    
    _output_message(str("%s - %s - %s" %  (datetime.datetime.now(), module, loglevel.name)), str(message))


class LOG(object):

    @staticmethod
    def DEBUG(module, message):
        if CONFIG.LOG_LEVEL <= LOGLEVEL.DEBUG:
            log_message(module, LOGLEVEL.DEBUG, message)

    @staticmethod
    def INFO(module, message):
        if CONFIG.LOG_LEVEL <= LOGLEVEL.INFO:
            log_message(module, LOGLEVEL.INFO, message)

    @staticmethod
    def WARNING(module, message):
        if CONFIG.LOG_LEVEL <= LOGLEVEL.WARNING:
            log_message(module, LOGLEVEL.WARNING, message)

    @staticmethod
    def ERROR(module, message):
        if CONFIG.LOG_LEVEL <= LOGLEVEL.ERROR:
            log_message(module, LOGLEVEL.ERROR, message)
