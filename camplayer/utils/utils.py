#!/usr/bin/python3

import subprocess
import re
import time

# Only supported revisions are listed at the moment
# Non supported devices includes:
#   - Devices without ethernet/WLAN 
#   - Devices older than model 2
# Source: https://www.raspberrypi.org/documentation/hardware/raspberrypi/revision-codes/README.md
pi_revisions = {
    "9000c1" : {"model": "Zero W",      "supported": True, "dual_hdmi": False, "hevc": False},
    "a01040" : {"model": "Zero W",      "supported": True, "dual_hdmi": False, "hevc": False},
    "a01041" : {"model": "2B",          "supported": True, "dual_hdmi": False, "hevc": False},
    "a21041" : {"model": "2B",          "supported": True, "dual_hdmi": False, "hevc": False},
    "a22042" : {"model": "2B",          "supported": True, "dual_hdmi": False, "hevc": False},
    "a02082" : {"model": "3B",          "supported": True, "dual_hdmi": False, "hevc": False},
    "a32082" : {"model": "3B",          "supported": True, "dual_hdmi": False, "hevc": False},
    "a22082" : {"model": "3B",          "supported": True, "dual_hdmi": False, "hevc": False},
    "a52082" : {"model": "3B",          "supported": True, "dual_hdmi": False, "hevc": False},
    "a22083" : {"model": "3B",          "supported": True, "dual_hdmi": False, "hevc": False},
    "a020d3" : {"model": "3B+",         "supported": True, "dual_hdmi": False, "hevc": False},
    "a03111" : {"model": "4B 1GB",      "supported": True, "dual_hdmi": True,  "hevc": True},
    "b03111" : {"model": "4B 2GB",      "supported": True, "dual_hdmi": True,  "hevc": True},
    "c03111" : {"model": "4B 4GB",      "supported": True, "dual_hdmi": True,  "hevc": True},
    "b03112" : {"model": "4B 2GB",      "supported": True, "dual_hdmi": True,  "hevc": True},
    "c03112" : {"model": "4B 4GB",      "supported": True, "dual_hdmi": True,  "hevc": True},
    "d03114" : {"model": "4B 8GB",      "supported": True, "dual_hdmi": True,  "hevc": True},
    "b03114" : {"model": "4B 2GB",      "supported": True, "dual_hdmi": True,  "hevc": True},
    "c03114" : {"model": "4B 4GB",      "supported": True, "dual_hdmi": True,  "hevc": True},
    "c03130" : {"model": "PI 400 4GB",  "supported": True, "dual_hdmi": True,  "hevc": True},
    "9020e0" : {"model": "3A+",         "supported": True, "dual_hdmi": False, "hevc": False},
}


def get_gpu_memory():
    """Get the amount of memory allocated to the GPU in MB"""

    try:
        response = subprocess.check_output(['vcgencmd', 'get_mem', 'gpu']).decode()

        if response:
            response = re.findall('\d+', str(response))
            return int(response[0])
    except:
        pass

    return 0


def get_hardware_info():
    """Get hardware info (SoC, HW revision, S/N, Model name)"""
    
    revision = ""
    serial = ""
    soc = ""
    model = ""
    dual_hdmi = False
    hevc_decoder = False
    supported = False

    try:
        response = subprocess.check_output(
            ['cat', '/proc/cpuinfo'], timeout=2).decode().splitlines()

        for line in response:
            if "revision" in line.lower():
                revision = line.split(':')[1].strip()
            elif "serial" in line.lower():
                serial = line.split(':')[1].strip()
            elif "hardware" in line.lower():
                soc = line.split(':')[1].strip()

        if revision:
            rev_map = pi_revisions.get(revision, model)

            if rev_map:
                model = rev_map.get("model")
                supported = rev_map.get('supported')
                dual_hdmi = rev_map.get('dual_hdmi')
                hevc_decoder = rev_map.get('hevc')
    except:
        pass

    return {'soc': soc, 'revision': revision, 'serial': serial, 'hevc': hevc_decoder,
            'model': model, 'supported': supported, 'dual_hdmi': dual_hdmi}


def get_system_info():
    """Get a description of this operation system""" 

    try:
        return str(subprocess.check_output(
            ['uname', '-a'], universal_newlines=True)).splitlines()[0]
    except:
        pass

    return ""


def kill_service(service, force=False):
    """Terminate all processes with a given name"""

    try:
        subprocess.Popen(['killall', '-15', service], shell=False,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).wait(timeout=2)
    except:
        pass

    if force:
        time.sleep(0.5)
        try:
            subprocess.Popen(['killall', '-9', service], shell=False,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).wait(timeout=2)
        except:
            pass


def terminate_process(PID, force=False):
    """Terminate a process by its"""

    try:
        subprocess.Popen(['kill', '-15', str(PID)], shell=False,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).wait(timeout=2)
    except:
        pass

    if force:
        time.sleep(0.5)
        try:
            subprocess.Popen(['kill', '-9', str(PID)], shell=False,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).wait(timeout=2)
        except:
            pass


def get_display_mode(display=2):
    """Get current diplay mode (display 2 = HDMI0, display 7 = HDMI1)"""

    hdmi_group  = 'Unknown'
    hdmi_mode   = 0
    res_width   = 0
    res_height  = 0
    framerate   = 0
    device_name = ""

    try:
        response = subprocess.check_output(
            ['tvservice', '--device', str(display), '--status'],
            stderr=subprocess.STDOUT).decode().splitlines()[0]

        tmp = re.search('^state.+(DMT|CEA).*\((\d+)\)[\s*\S*]* (\d+)x(\d+).+@ (\d+)', response)
        if tmp:
            hdmi_group  = tmp.group(1)
            hdmi_mode   = int(tmp.group(2))
            res_width   = int(tmp.group(3))
            res_height  = int(tmp.group(4))
            framerate   = int(tmp.group(5))

        response = subprocess.check_output(
            ['tvservice', '--device', str(display), '--name'],
            timeout=2, stderr=subprocess.STDOUT).decode()

        if "device_name=" in response:
            device_name = response.split('=')[1].strip()
    except:
        pass

    return {'hdmi_group': hdmi_group, 'hdmi_mode': hdmi_mode, 'res_width': res_width,
            'res_height': res_height, 'framerate': framerate, 'device_name': device_name}


def os_package_installed(package):
    """Check if some linux package/application is installed"""

    try:
        subprocess.check_output(['which', package],
            stderr=subprocess.STDOUT).decode().splitlines()[0]

        return True

    except:
        pass

    return False
