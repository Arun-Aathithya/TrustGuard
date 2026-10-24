#!/usr/bin/env python3
"""
Pretend to be the ESP32 so you can test broker -> backend -> dashboard WITHOUT the board.
This proves the software path only; it does NOT prove your physical sensors/firmware work.
WARNING: the backend cannot tell these messages from real ones. They are stored as hardware readings of the sensor
you point them at, so use a throw-away sensor (or remove it afterwards) and never leave this running.

  python tools/fake_esp32.py ... --topic trustguard/sensors/1/temperature/7 --sensor-id 7 --sensor-type temperature
(--topic = the sensor's mqtt_topic from the dashboard; without it the old per-type topics are used.)

  pip install paho-mqtt
  python tools/fake_esp32.py --host localhost --port 8883 --tls --cafile ca.crt -u esp32 -P <pw> --machine 1 --device ESP32-A1
  Options: --case normal|null|malformed|duplicate|old|all   --count 20   --interval 2
Register ESP32-A1 (temperature + vibration) for the machine first (Hardware page).
"""
import argparse, json, random, time
from datetime import datetime, timedelta, timezone

import paho.mqtt.client as mqtt


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--host", default="localhost"); a.add_argument("--port", type=int, default=1883)
    a.add_argument("--tls", action="store_true"); a.add_argument("--cafile")
    a.add_argument("-u", "--user"); a.add_argument("-P", "--password")
    a.add_argument("--machine", type=int, default=1); a.add_argument("--device", default="ESP32-A1")
    a.add_argument("--case", default="normal", choices=["normal", "null", "malformed", "duplicate", "old", "all"])
    a.add_argument("--count", type=int, default=10); a.add_argument("--interval", type=float, default=2.0)
    a.add_argument("--vibration-scale", type=float, default=0.25, help="typical healthy RMS in m/s^2 to emit")
    a.add_argument("--topic", help="publish everything to this exact topic (a configured sensor's mqtt_topic)")
    a.add_argument("--sensor-id", type=int, help="include sensor_id in the payload")
    a.add_argument("--sensor-type", default="temperature", choices=["temperature", "vibration"], help="with --topic: the type to simulate")
    o = a.parse_args()

    try:
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"fake-{o.device}")
    except AttributeError:
        c = mqtt.Client(client_id=f"fake-{o.device}")
    if o.user:
        c.username_pw_set(o.user, o.password)
    if o.tls:
        c.tls_set(ca_certs=o.cafile)  # verification stays on
    c.connect(o.host, o.port, 30); c.loop_start()

    def pub(kind, payload):
        topic = o.topic or f"trustguard/sensors/{o.machine}/{kind}"
        r = c.publish(topic, payload, qos=1); r.wait_for_publish()

    def msg(kind, value, ts=None):
        body = {"device_id": o.device, "sensor_type": kind, "value": value,
                "timestamp": (ts or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        if o.sensor_id:
            body["sensor_id"] = o.sensor_id
        return json.dumps(body)

    cases = ["normal", "null", "malformed", "duplicate", "old"] if o.case == "all" else [o.case]
    for case in cases:
        print(f"--- {case}")
        for i in range(o.count if case == "normal" else 2):
            t = round(random.gauss(66, 0.4), 2); v = round(abs(random.gauss(o.vibration_scale, 0.03)), 3)
            if case == "normal" and o.topic:
                pub(o.sensor_type, msg(o.sensor_type, t if o.sensor_type == "temperature" else v))
            elif case == "normal":
                pub("temperature", msg("temperature", t)); pub("vibration", msg("vibration", v))
            elif case == "null":
                pub("temperature", msg("temperature", None))
            elif case == "malformed":
                pub("temperature", "this is not json"); pub("temperature", json.dumps({"device_id": o.device}))
            elif case == "duplicate":
                same = datetime.now(timezone.utc).replace(microsecond=0)
                pub("temperature", msg("temperature", t, same))
            elif case == "old":
                pub("temperature", msg("temperature", t, datetime.now(timezone.utc) - timedelta(seconds=90)))
            time.sleep(o.interval)
    c.loop_stop(); c.disconnect()
    print("Done. Check the dashboard and GET /api/hardware/events for the rejected/delayed ones.")


if __name__ == "__main__":
    main()
