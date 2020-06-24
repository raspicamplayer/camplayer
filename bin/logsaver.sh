#!/bin/bash

LOGFILE="camplayer.tail.log"
DIRECTORY_BOOT="/boot/"
DIRECTORY_ROOT="/usr/local/share/camplayer"
MAXSIZE=500000
NLINES=500

check_logfile() {
    local path=$1$2
    
    if [ ! -f "$path" ]; then
        touch $path
    else
        local filesize=$(stat -c%s "$path")
        
        if [ $filesize -gt $MAXSIZE ]; then
            echo "" > $path
        fi
    fi
    
    echo "" >> $path
    echo "###################### Last $NLINES lines of logfile ######################" >> $path
    journalctl --unit=camplayer.service | tail -n $NLINES >> $path
}

if [ -d "$DIRECTORY_BOOT" ]; then
    check_logfile $DIRECTORY_BOOT $LOGFILE
else
    check_logfile $DIRECTORY_ROOT $LOGFILE
fi

