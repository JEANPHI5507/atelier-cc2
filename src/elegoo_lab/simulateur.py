"""A simulated Centauri Carbon 2, to try the workshop without a printer: a tiny MQTT 3.1.1 broker plus a fake printer.

Speaks the CC2 protocol documented by pycentauri (topics under ``elegoo/<sn>/``, JSON-RPC over MQTT), with a drawn
camera, a CANVAS of four spools, files and prints that run in fast motion. Not a faithful firmware model: the tests
use it too. ``cc2 simulateur`` starts it with the workshop on a demo library of its own.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any

SIM_HOST = "127.0.0.1"
SIM_PORT = int(os.environ.get("CC2_SIM_PORT", 1884))  # 1883 is often taken by a local broker
SIM_HTTP_PORT = int(os.environ.get("CC2_SIM_HTTP_PORT", 18080))  # stands in for the printer's HTTP :80 upload endpoint
SIM_SERIAL = "SIMCC20000001"
SIM_CODE = "sim123"

log = logging.getLogger("fakeprinter")

# machine_status / sub_status values understood by pycentauri
IDLE, PRINTING = 1, 2
SUB_PAUSED, SUB_DONE = 2502, 2077

FILES = [
    {"filename": "benchy_0.2mm_PLA.3mf", "size": 4_200_000, "layer": 240, "print_time": 60 * 95},
    {"filename": "cube_20mm.gcode", "size": 310_000, "layer": 100, "print_time": 60 * 22},
]
# the user's first spools: a PLA Silk set (white, shiny gold, Christmas red, Christmas green)
COLORS = ["#E9E9E7", "#F2A900", "#D22630", "#008755"]


def _topic_match(flt: str, topic: str) -> bool:
    f, t = flt.split("/"), topic.split("/")
    for i, part in enumerate(f):
        if part == "#":
            return True
        if i >= len(t) or (part != "+" and part != t[i]):
            return False
    return len(f) == len(t)


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b, n = n % 128, n // 128
        out.append(b | 128 if n else b)
        if not n:
            return bytes(out)


def _pkt(first: int, body: bytes) -> bytes:
    return bytes([first]) + _varint(len(body)) + body


class Sim:
    def __init__(self, port: int = SIM_PORT, print_seconds: float = 90.0,
                 http_port: int = SIM_HTTP_PORT) -> None:
        self.port = port
        self.http_port = http_port
        self.sn = SIM_SERIAL
        self.code = SIM_CODE
        self.print_seconds = print_seconds
        self.clients: dict[asyncio.StreamWriter, list[str]] = {}
        self.push_id = 0
        self.t0 = time.monotonic()
        self.s: dict[str, Any] = {
            "status": IDLE, "sub": 0, "progress": 0, "file": "", "t_print": 0.0,
            "nozzle": 24.0, "nozzle_t": 0.0, "bed": 23.0, "bed_t": 0.0,
            "speed_mode": 1, "light": 0, "fan": 0, "aux": 0, "box": 0,
            "auto_refill": True, "active_tray": -1, "history": [],
        }

    # --- state ---------------------------------------------------------------

    def status_result(self) -> dict[str, Any]:
        s = self.s
        printing = s["status"] == PRINTING
        layer = int(s.get("layers", 100) * s["progress"] / 100) if printing else 0
        left = int((100 - s["progress"]) / 100 * self.print_seconds) if printing else 0
        return {
            "gcode_move": {"speed": 6000 if printing else 0, "speed_mode": s["speed_mode"],
                           "x": 128.0, "y": 128.0, "z": 0.2 + layer * 0.2, "extruder": 0.0},
            "extruder": {"temperature": round(s["nozzle"], 1), "target": s["nozzle_t"],
                         "filament_detect_enable": 1, "filament_detected": 1},
            "heater_bed": {"temperature": round(s["bed"], 1), "target": s["bed_t"]},
            "fans": {k: {"speed": v} for k, v in
                     {"fan": s["fan"], "aux_fan": s["aux"], "box_fan": s["box"],
                      "controller_fan": 120, "heater_fan": 255}.items()},
            "machine_status": {"status": s["status"], "sub_status": s["sub"],
                               "sub_status_reason_code": 0, "exception_status": [],
                               "progress": int(s["progress"])},
            "print_status": {"state": "printing" if printing else "standby",
                             "filename": s["file"], "current_layer": layer,
                             "print_duration": int(s["t_print"]), "remaining_time_sec": left,
                             "total_duration": int(s["t_print"]) + left, "uuid": "sim-task"},
            "led": {"status": s["light"]},
            "tool_head": {"homed_axes": "xyz"},
            "ztemperature_sensor": {"temperature": 31.0, "measured_max_temperature": 33.0,
                                    "measured_min_temperature": 22.0},
            "external_device": {"camera": False, "u_disk": False, "type": "sim"},
        }

    def canvas_result(self) -> dict[str, Any]:
        names = ["PLA Silk Blanc", "PLA Silk Or", "PLA Silk Rouge", "PLA Silk Vert"]
        # field names, 1-4 numbering and status 2 (loaded) as in Elegoo's LAN SDK
        trays = [{"tray_id": i + 1, "filament_name": names[i], "filament_type": "PLA", "filament_color": COLORS[i],
                  "filament_code": f"SIM-{i}", "brand": "Elegoo", "min_nozzle_temp": 190,
                  "max_nozzle_temp": 230, "status": 2} for i in range(4)]
        return {"error_code": 0, "canvas_info": {
            "active_canvas_id": 0, "active_tray_id": self.s["active_tray"],
            "auto_refill": self.s["auto_refill"],
            "canvas_list": [{"canvas_id": 0, "connected": 1, "tray_list": trays}]}}

    def handle(self, method: int, p: dict[str, Any]) -> dict[str, Any]:
        s = self.s
        ok: dict[str, Any] = {"error_code": 0}
        if method == 1001:
            return {**ok, "hostname": "CC2-SIM", "machine_model": "Centauri Carbon 2 (SIMULATEUR)",
                    "sn": self.sn, "ip": SIM_HOST, "protocol_version": "1.0",
                    "software_version": {"ota_version": "SIM.00.01"}}
        if method == 1002:
            return {**ok, **self.status_result()}
        if method == 1020:
            if s["status"] != IDLE:
                return {"error_code": 1010}
            name = p.get("filename", "?")
            cfg = p.get("config") or {}
            trays = {t["tray_id"] for t in self.canvas_result()["canvas_info"]["canvas_list"][0]["tray_list"]}
            if any(m.get("tray_id") not in trays for m in cfg.get("slot_map", [])):
                return {"error_code": 1003}   # like a real refusal: unknown spool
            self.last_start = p                # tests read what a client really sent
            layers = next((f["layer"] for f in FILES if f["filename"] == name), 100)
            s.update(status=PRINTING, sub=0, progress=0, t_print=0.0, file=name, layers=layers,
                     nozzle_t=220.0, bed_t=60.0)
            return ok
        if method == 1021 and s["status"] == PRINTING:
            s["sub"] = SUB_PAUSED
            return ok
        if method == 1023:
            if s["sub"] != SUB_PAUSED:
                return {"error_code": 1010}
            s["sub"] = 0
            return ok
        if method == 1022:
            if s["status"] != PRINTING:
                return {"error_code": 1010}
            self._finish("cancelled")
            return ok
        if method == 1028:
            s["nozzle_t"] = float(p.get("extruder", s["nozzle_t"]))
            s["bed_t"] = float(p.get("heater_bed", s["bed_t"]))
            return ok
        if method == 1029:
            s["light"] = int(p.get("power", 0))
            return ok
        if method == 1030:
            s["fan"], s["aux"], s["box"] = (int(p.get(k, v)) for k, v in
                                            (("fan", s["fan"]), ("aux_fan", s["aux"]), ("box_fan", s["box"])))
            return ok
        if method == 1031:
            if s["status"] != PRINTING:
                return {"error_code": 1010}
            s["speed_mode"] = int(p.get("mode", 1))
            return ok
        if method == 1036:
            return {**ok, "history_task_list": s["history"]}
        if method == 1044:
            return {**ok, "file_list": FILES, "offset": 0, "total": len(FILES)}
        if method == 1047:
            names = set(p.get("file_path", []))
            FILES[:] = [f for f in FILES if f["filename"] not in names]
            return ok
        if method == 1048:
            return {**ok, "total_bytes": 8_000_000_000, "used_bytes": 1_200_000_000}
        if method == 2004:
            s["auto_refill"] = bool(p.get("auto_refill"))
            return ok
        if method == 2005:
            return self.canvas_result()
        return {"error_code": 1010}

    def _finish(self, how: str) -> None:
        s = self.s
        s["history"].append({"task_name": s["file"], "task_status": 1 if how == "done" else 2,
                             "begin_time": int(time.time() - s["t_print"]), "end_time": int(time.time())})
        s.update(status=IDLE, sub=0, progress=0, file="", nozzle_t=0.0, bed_t=0.0)

    def tick(self, dt: float) -> None:
        s = self.s
        for cur, tgt, rate in (("nozzle", "nozzle_t", 40.0), ("bed", "bed_t", 12.0)):
            goal = s[tgt] or 24.0
            step = rate * dt
            s[cur] += max(-step, min(step, goal - s[cur]))
        if s["status"] == PRINTING and s["sub"] == 0 and s["nozzle"] >= s["nozzle_t"] - 3:
            s["t_print"] += dt
            s["progress"] = min(100.0, s["progress"] + 100 * dt / self.print_seconds)
            if s["progress"] >= 100:
                self._finish("done")

    # --- MQTT plumbing ------------------------------------------------------

    async def _send(self, w: asyncio.StreamWriter, topic: str, payload: dict[str, Any]) -> None:
        t = topic.encode()
        w.write(_pkt(0x30, len(t).to_bytes(2, "big") + t + json.dumps(payload).encode()))
        await w.drain()

    async def _publish(self, topic: str, payload: dict[str, Any]) -> None:
        for w, filters in list(self.clients.items()):
            if any(_topic_match(f, topic) for f in filters):
                try:
                    await self._send(w, topic, payload)
                except (ConnectionError, OSError):
                    self.clients.pop(w, None)

    async def _on_publish(self, topic: str, data: dict[str, Any]) -> None:
        base = f"elegoo/{self.sn}"
        if topic == f"{base}/api_register":
            await self._publish(f"{base}/{data['request_id']}/register_response",
                                {"client_id": data["client_id"], "error": "ok"})
        elif topic.endswith("/api_request") and topic.startswith(base + "/"):
            reply = topic[: -len("api_request")] + "api_response"
            if data.get("type") == "PING":
                await self._publish(reply, {"type": "PONG"})
            elif "method" in data:
                res = self.handle(int(data["method"]), data.get("params") or {})
                await self._publish(reply, {"id": data["id"], "method": data["method"], "result": res})

    async def _client(self, r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
        try:
            while True:
                first = (await r.readexactly(1))[0]
                mult, length = 1, 0
                while True:
                    b = (await r.readexactly(1))[0]
                    length += (b & 127) * mult
                    mult *= 128
                    if not b & 128:
                        break
                body = await r.readexactly(length) if length else b""
                kind = first >> 4
                if kind == 1:  # CONNECT: check credentials
                    i = 2 + int.from_bytes(body[:2], "big")  # after protocol name
                    flags = body[i + 1]
                    i += 4  # level, flags, keepalive
                    i += 2 + int.from_bytes(body[i:i + 2], "big")  # client id
                    user = pw = ""
                    if flags & 0x80:
                        n = int.from_bytes(body[i:i + 2], "big"); user = body[i + 2:i + 2 + n].decode(); i += 2 + n
                    if flags & 0x40:
                        n = int.from_bytes(body[i:i + 2], "big"); pw = body[i + 2:i + 2 + n].decode()
                    good = user == "elegoo" and pw == self.code
                    w.write(_pkt(0x20, bytes([0, 0 if good else 5])))
                    if not good:
                        await w.drain()
                        return
                    self.clients[w] = []
                elif kind == 8:  # SUBSCRIBE
                    pid, i, granted = body[:2], 2, bytearray()
                    while i < len(body):
                        n = int.from_bytes(body[i:i + 2], "big")
                        self.clients[w].append(body[i + 2:i + 2 + n].decode())
                        i += 3 + n
                        granted.append(0)
                    w.write(_pkt(0x90, pid + bytes(granted)))
                elif kind == 3:  # PUBLISH
                    n = int.from_bytes(body[:2], "big")
                    topic, i = body[2:2 + n].decode(), 2 + n
                    if (first >> 1) & 3:
                        w.write(_pkt(0x40, body[i:i + 2]))
                        i += 2
                    try:
                        await self._on_publish(topic, json.loads(body[i:]))
                    except (json.JSONDecodeError, KeyError):
                        pass
                elif kind == 12:
                    w.write(_pkt(0xD0, b""))
                elif kind == 14:
                    return
                await w.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            self.clients.pop(w, None)
            w.close()

    async def _loop(self) -> None:
        last = time.monotonic()
        while True:
            await asyncio.sleep(1.0)
            now = time.monotonic()
            self.tick(now - last)
            last = now
            self.push_id += 1
            await self._publish(f"elegoo/{self.sn}/api_status",
                                {"id": self.push_id, "method": 6000, "result": self.status_result()})

    async def _http(self, r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
        """Minimal PUT /upload (chunked Content-Range) like the CC2's HTTP API."""
        try:
            head = (await r.readuntil(b"\r\n\r\n")).decode("latin1").split("\r\n")
            method, path, _ = head[0].split(" ", 2)
            h = {k.lower(): v for k, v in (l.split(": ", 1) for l in head[1:] if ": " in l)}
            body = await r.readexactly(int(h.get("content-length", 0)))
            status, out = 404, b"{}"
            if method == "GET" and path.startswith("/video"):   # MJPEG like the CC2 camera (:8080/video)
                w.write(b"HTTP/1.1 200 OK\r\nContent-Type: multipart/x-mixed-replace; boundary=frame\r\n\r\n")
                while True:
                    jpg = self.camera_frame()
                    w.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(jpg)).encode()
                            + b"\r\n\r\n" + jpg + b"\r\n")
                    await w.drain()
                    await asyncio.sleep(0.5)
            if method == "GET" and path.startswith("/system/info"):  # serial bootstrap, like the real CC2
                ok = f"X-Token={self.code}" in path
                status = 200 if ok else 401
                out = json.dumps({"system_info": {"sn": self.sn, "model": "Centauri Carbon 2 (SIMULATEUR)"}}).encode() if ok else b"{}"
            elif method == "PUT" and path.startswith("/upload"):
                if h.get("x-token") != self.code:
                    status = 401
                else:
                    rng = h.get("content-range", "bytes 0-0/0").split()[-1]
                    span, total = rng.split("/")
                    name = h.get("x-file-name", "upload.gcode")
                    self.uploads.setdefault(name, bytearray()).extend(body)
                    if int(span.split("-")[1]) + 1 >= int(total):
                        data = bytes(self.uploads.pop(name))
                        layers = data.count(b";LAYER_CHANGE") or 100
                        FILES[:] = [f for f in FILES if f["filename"] != name]
                        FILES.append({"filename": name, "size": len(data), "layer": layers, "print_time": 3600})
                    status, out = 200, b'{"error_code": 0}'
            w.write(f"HTTP/1.1 {status} X\r\nContent-Length: {len(out)}\r\nContent-Type: application/json\r\n\r\n".encode() + out)
            await w.drain()
        except (asyncio.IncompleteReadError, ConnectionError, ValueError):
            pass
        finally:
            w.close()

    def camera_frame(self) -> bytes:
        """A drawn view of the chamber: the plate, and the part growing with the progress."""
        import io
        from PIL import Image, ImageDraw
        s = self.s
        img = Image.new("RGB", (640, 360), (52, 56, 62))
        d = ImageDraw.Draw(img)
        d.polygon([(90, 300), (550, 300), (480, 210), (160, 210)], fill=(70, 74, 80))       # plate
        for i in range(9):
            x = 160 + i * 40
            d.line([(x, 210), (90 + i * 57.5, 300)], fill=(82, 86, 92))
        h = int(110 * s["progress"] / 100) if s["status"] == PRINTING else 0
        if h:
            d.rectangle([280, 262 - h, 360, 262], fill=(229, 57, 53))
            d.polygon([(280, 262 - h), (360, 262 - h), (372, 252 - h), (292, 252 - h)], fill=(240, 90, 80))
            nx = 300 + int(40 * ((time.time() * 0.7) % 1))
            d.rectangle([nx - 14, 230 - h, nx + 14, 252 - h], fill=(200, 200, 205))          # print head
        d.text((12, 10), f"SIMULATEUR  {time.strftime('%H:%M:%S')}  {s['progress']:.0f} %", fill=(220, 220, 220))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=70)
        return buf.getvalue()

    async def serve(self) -> None:
        self.uploads: dict[str, bytearray] = {}
        server = await asyncio.start_server(self._client, "127.0.0.1", self.port)
        http = await asyncio.start_server(self._http, "127.0.0.1", self.http_port)
        log.info("simulator MQTT on 127.0.0.1:%d, upload HTTP on :%d (sn=%s, code=%s)",
                 self.port, self.http_port, self.sn, self.code)
        async with server, http:
            await asyncio.gather(server.serve_forever(), http.serve_forever(), self._loop())


def patch_pycentauri() -> None:
    """Point pycentauri's CC2 client at the simulator (non-standard port, no HTTP bootstrap)."""
    import pycentauri.camera as camera
    import pycentauri.cc2 as cc2
    import pycentauri.connect as connect

    camera.CAMERA_PORT_CC2 = SIM_HTTP_PORT   # the simulator draws its own camera

    async def _port_open(host: str, port: int, timeout: float = 2.0) -> bool:
        return True

    async def _fetch_serial(host: str, access_code: str, timeout: float = 5.0) -> str:
        return SIM_SERIAL

    import pycentauri.upload as upload

    upload.UPLOAD_PORT = SIM_HTTP_PORT
    cc2.MQTT_PORT = SIM_PORT
    cc2._fetch_serial = _fetch_serial
    connect._port_open = _port_open


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=90.0, help="length of a fake print")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    asyncio.run(Sim(print_seconds=args.seconds).serve())


if __name__ == "__main__":
    main()
