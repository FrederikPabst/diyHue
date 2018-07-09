from pprint import pprint
import requests
import json
from time import sleep
from threading import Thread
from datetime import datetime
import socket

from subprocess import check_output

from huebridgeemulator.tools.deconz import scanDeconz
from huebridgeemulator.device.tradfri import discover_tradfri
from huebridgeemulator.device.yeelight import discover_yeelight
from huebridgeemulator.device.tplink import discover_tplink
from huebridgeemulator.tools.colors import convert_rgb_xy, convert_xy
from huebridgeemulator.http.client import sendRequest

LIGHT_TYPES = \
{"LCT015": {"state": {"on": False,
                      "bri": 200,
                      "hue": 0,
                      "sat": 0,
                      "xy": [0.0, 0.0],
                      "ct": 461,
                      "alert": "none",
                      "effect": "none",
                      "colormode": "ct",
                      "reachable": True},
            "type": "Extended color light",
            "swversion": "1.29.0_r21169"},
"LST001": {"state": {"on": False,
                     "bri": 200,
                     "hue": 0,
                     "sat": 0,
                     "xy": [0.0, 0.0],
                     "ct": 461,
                     "alert": "none",
                     "effect": "none",
                     "colormode": "ct",
                     "reachable": True},
           "type": "Color light",
           "swversion": "66010400"},
"LWB010": {"state": {"on": False,
                     "bri": 254,
                     "alert": "none",
                     "reachable": True},
           "type": "Dimmable light",
           "swversion": "1.15.0_r18729"},
"LTW001": {"state": {"on": False,
                     "colormode": "ct",
                     "alert": "none",
                     "reachable": True,
                     "bri": 254,
                     "ct": 230},
           "type": "Color temperature light",
           "swversion": "5.50.1.19085"},
"Plug 01": {"state": {"on": False,
                      "alert": "none",
                      "reachable": True},
            "type": "On/Off plug-in unit",
            "swversion": "V1.04.12"}
}

def update_all_lights(registry):
    """Apply last state on startup to all bulbs,
    usefull if there was a power outage.
    """
    for light in registy.lights.values():
        payload = {}
        payload["on"] = light.state.on
        if payload["on"] and hasattr(light.state, 'bri'):
            payload["bri"] = light.state.bri
        light.send_request(payload)
        sleep(0.5)
        light.logger.debug("update status for light %s", light)


def getIpAddress():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    return s.getsockname()[0]


def scanForLights(conf_obj, new_lights): #scan for ESP8266 lights and strips
    Thread(target=discover_yeelight, args=[conf_obj]).start()
    Thread(target=discover_tplink, args=[conf_obj]).start()
    #return all host that listen on port 80
    device_ips = check_output("nmap  " + getIpAddress() + "/24 -p80 --open -n | grep report | cut -d ' ' -f5", shell=True).decode('utf-8').split("\n")
    pprint(device_ips)
    del device_ips[-1] #delete last empty element in list
    for ip in device_ips:
        try:
            if ip != getIpAddress():
                response = requests.get("http://" + ip + "/detect", timeout=3)
                if response.status_code == 200:
                    device_data = json.loads(response.text)
                    pprint(device_data)
                    if "hue" in device_data:
                        print(ip + " is a hue " + device_data['hue'])
                        device_exist = False
                        for light in conf_obj.bridge["lights"].keys():
                            if conf_obj.bridge["lights"][light]["uniqueid"].startswith( device_data["mac"] ):
                                device_exist = True
                                conf_obj.bridge["lights_address"][light]["ip"] = ip
                        if not device_exist:
                            light_name = "Hue " + device_data["hue"] + " " + device_data["modelid"]
                            if "name" in device_data:
                                light_name = device_data["name"]
                            print("Add new light: " + light_name)
                            for x in range(1, int(device_data["lights"]) + 1):
                                new_light_id = nextFreeId("lights")
                                conf_obj.bridge["lights"][new_light_id] = {"state": LIGHT_TYPES[device_data["modelid"]]["state"], "type": LIGHT_TYPES[device_data["modelid"]]["type"], "name": light_name if x == 1 else light_name + " " + str(x), "uniqueid": device_data["mac"] + "-" + str(x), "modelid": device_data["modelid"], "manufacturername": "Philips", "swversion": LIGHT_TYPES[device_data["modelid"]]["swversion"]}
                                new_lights.update({new_light_id: {"name": light_name if x == 1 else light_name + " " + str(x)}})
                                conf_obj.bridge["lights_address"][new_light_id] = {"ip": ip, "light_nr": x, "protocol": "native"}
        except Exception as exp:
#            raise exp
            print("ip " + ip + " is unknow device")
    scanDeconz(conf_obj)
    discover_tradfri(registry)
    conf_obj.save()


def sendLightRequest(conf_obj, light, data):
    bridge_config = conf_obj.bridge
    payload = {}
    if light in bridge_config["lights_address"]:
        if bridge_config["lights_address"][light]["protocol"] == "native": #ESP8266 light or strip
            url = "http://" + bridge_config["lights_address"][light]["ip"] + "/set?light=" + str(bridge_config["lights_address"][light]["light_nr"]);
            method = 'GET'
            for key, value in data.items():
                if key == "xy":
                    url += "&x=" + str(value[0]) + "&y=" + str(value[1])
                else:
                    url += "&" + key + "=" + str(value)
        elif bridge_config["lights_address"][light]["protocol"] in ["deconz"]: #Original Hue light or Deconz light
            url = "http://" + bridge_config["lights_address"][light]["ip"] + "/api/" + bridge_config["lights_address"][light]["username"] + "/lights/" + bridge_config["lights_address"][light]["light_id"] + "/state"
            method = 'PUT'
            payload.update(data)

        elif bridge_config["lights_address"][light]["protocol"] == "domoticz": #Domoticz protocol
            url = "http://" + bridge_config["lights_address"][light]["ip"] + "/json.htm?type=command&param=switchlight&idx=" + bridge_config["lights_address"][light]["light_id"];
            method = 'GET'
            for key, value in data.items():
                if key == "on":
                    if value:
                        url += "&switchcmd=On"
                    else:
                        url += "&switchcmd=Off"
                elif key == "bri":
                    url += "&switchcmd=Set%20Level&level=" + str(round(float(value)/255*100)) # domoticz range from 0 to 100 (for zwave devices) instead of 0-255 of bridge

        elif bridge_config["lights_address"][light]["protocol"] == "milight": #MiLight bulb
            url = "http://" + bridge_config["lights_address"][light]["ip"] + "/gateways/" + bridge_config["lights_address"][light]["device_id"] + "/" + bridge_config["lights_address"][light]["mode"] + "/" + str(bridge_config["lights_address"][light]["group"]);
            method = 'PUT'
            for key, value in data.items():
                if key == "on":
                    payload["status"] = value
                elif key == "bri":
                    payload["brightness"] = value
                elif key == "ct":
                    payload["color_temp"] = int(value / 1.6 + 153)
                elif key == "hue":
                    payload["hue"] = value / 180
                elif key == "sat":
                    payload["saturation"] = value * 100 / 255
                elif key == "xy":
                    payload["color"] = {}
                    (payload["color"]["r"], payload["color"]["g"], payload["color"]["b"]) = convert_xy(value[0], value[1], bridge_config["lights"][light]["state"]["bri"])
            print(json.dumps(payload))
        elif bridge_config["lights_address"][light]["protocol"] in ["yeelight", "hue"]: # new format bulb
            raise Exception("Yeelight light are now a class")
        elif bridge_config["lights_address"][light]["protocol"] == "ikea_tradfri": #IKEA Tradfri bulb
            url = "coaps://" + bridge_config["lights_address"][light]["ip"] + ":5684/15001/" + str(bridge_config["lights_address"][light]["device_id"])
            for key, value in data.items():
                if key == "on":
                    payload["5850"] = int(value)
                elif key == "transitiontime":
                    payload["5712"] = value
                elif key == "bri":
                    payload["5851"] = value
                elif key == "ct":
                    if value < 270:
                        payload["5706"] = "f5faf6"
                    elif value < 385:
                        payload["5706"] = "f1e0b5"
                    else:
                        payload["5706"] = "efd275"
                elif key == "xy":
                    payload["5709"] = int(value[0] * 65535)
                    payload["5710"] = int(value[1] * 65535)
            if "hue" in data or "sat" in data:
                if("hue" in data):
                    hue = data["hue"]
                else:
                    hue = bridge_config["lights"][light]["state"]["hue"]
                if("sat" in data):
                    sat = data["sat"]
                else:
                    sat = bridge_config["lights"][light]["state"]["sat"]
                if("bri" in data):
                    bri = data["bri"]
                else:
                    bri = bridge_config["lights"][light]["state"]["bri"]
                rgbValue = hsv_to_rgb(hue, sat, bri)
                xyValue = convert_rgb_xy(rgbValue[0], rgbValue[1], rgbValue[2])
                payload["5709"] = int(xyValue[0] * 65535)
                payload["5710"] = int(xyValue[1] * 65535)
            if "5850" in payload and payload["5850"] == 0:
                payload.clear() #setting brightnes will turn on the ligh even if there was a request to power off
                payload["5850"] = 0
            elif "5850" in payload and "5851" in payload: #when setting brightness don't send also power on command
                del payload["5850"]

        try:
            if bridge_config["lights_address"][light]["protocol"] == "ikea_tradfri":
                if "5712" not in payload:
                    payload["5712"] = 4 #If no transition add one, might also add check to prevent large transitiontimes
                    check_output("./coap-client-linux -m put -u \"" + bridge_config["lights_address"][light]["identity"] + "\" -k \"" + bridge_config["lights_address"][light]["preshared_key"] + "\" -e '{ \"3311\": [" + json.dumps(payload) + "] }' \"" + url + "\"", shell=True)
            elif bridge_config["lights_address"][light]["protocol"] in ["hue", "deconz"]:
                if "xy" in payload:
                    sendRequest(url, method, json.dumps({"on": True, "xy": payload["xy"]}))
                    del(payload["xy"])
                    sleep(0.6)
                elif "ct" in payload:
                    sendRequest(url, method, json.dumps({"on": True, "ct": payload["ct"]}))
                    del(payload["ct"])
                    sleep(0.6)
                sendRequest(url, method, json.dumps(payload))
            else:
                sendRequest(url, method, json.dumps(payload))
        except Exception as exp:
            bridge_config["lights"][light]["state"]["reachable"] = False
            print("request error")
            raise(exp)
        else:
            bridge_config["lights"][light]["state"]["reachable"] = True
            print("LightRequest: " + url)
