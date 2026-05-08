# Roomba 650 UART Wiring & Communication Guide

Everything you need to know to wire up and talk to the Roomba over serial.

---

## The Roomba 650 Serial Port

The Roomba 650 has a **Mini-DIN 7-pin connector** on its side, also called
the "Serial Port" or "Cargo Bay Connector."  This is the interface we use.

### Pin Layout

Looking at the connector face-on from outside the Roomba:

```
        ┌─────────┐
        │  7 6 5  │
        │ 4     3 │
        │  2   1  │
        └─────────┘

Pin 1 — Vpwr  (unregulated battery voltage, 14.4V — DO NOT CONNECT)
Pin 2 — Vpwr  (same)
Pin 3 — RXD   ← receives data FROM your computer
Pin 4 — TXD   → sends data TO your computer
Pin 5 — BRC   (Baud Rate Change — leave disconnected)
Pin 6 — GND   ← common ground
Pin 7 — RTS   ← Request To Send (wakeup pin)
```

> **⚠️ Warning:** Pin 1 and 2 are at raw battery voltage (~14.4V).
> **Do NOT** connect these to anything. Only use pins 3, 4, 6, and 7.

---

## Wiring to a USB-UART Adapter

| Roomba Pin | Signal | USB-UART Adapter |
|------------|--------|------------------|
| Pin 3      | RXD    | TXD              |
| Pin 4      | TXD    | RXD              |
| Pin 6      | GND    | GND              |
| Pin 7      | RTS    | RTS              |

> **Note:** RXD and TXD are crossed.  Roomba's RXD connects to adapter's TXD.
> This is standard RS-232 crossover — TX on one side goes to RX on the other.

### Recommended USB-UART Adapters

| Adapter     | Chip      | Notes                                         |
|-------------|-----------|-----------------------------------------------|
| FTDI FT232R | FT232     | Best quality, reliable RTS control, 5V        |
| CP2102      | CP2102    | Very common, cheap, good Linux support        |
| CH340G      | CH340     | Cheap, works, occasional driver issues        |

> **Avoid:** Adapters that don't expose the RTS pin. You **need** RTS for wakeup.

---

## Baud Rate

The Roomba 650 defaults to **115200 baud** after a cold boot / power cycle.

- `8 data bits, no parity, 1 stop bit` (8N1) — standard
- Do NOT change the baud rate unless you have a specific reason

If you're getting garbage or no response, try **19200** — some early 650
units shipped with a different default.

---

## The RTS Wakeup Signal

The Roomba enters a low-power **sleep mode** after ~5 minutes of inactivity.
When it's sleeping, it **ignores all serial data**.

To wake it up, you must pulse the **RTS pin LOW** for at least 100ms.

### How It Works

```
RTS line state:

HIGH ─────────────────┐              ┌──────────────────
                      │              │
LOW                   └──────────────┘
                      ←── ≥100ms ───→
                      ↑              ↑
                   Assert          Deassert
                  (wake start)    (wake end)
```

In Python with pyserial:

```python
import serial, time

ser = serial.Serial("/dev/ttyUSB0", 115200, timeout=1.0)

# Pull RTS LOW (True = asserted = LOW on most adapters)
ser.setRTS(True)
time.sleep(0.150)     # hold for 150ms

# Release RTS HIGH
ser.setRTS(False)
time.sleep(0.500)     # wait 500ms for Roomba to wake up
```

> **Important:** On pyserial, `setRTS(True)` drives the pin **LOW** (assert).
> This is because RS-232 convention uses inverted logic for control signals.
> Different adapters may behave differently — if wakeup doesn't work,
> try `setRTS(False)` instead.

---

## OI Startup Sequence

After wakeup, you MUST send these commands in order:

```
1. START  (opcode 128)  → enters Passive mode
   Wait ≥ 200ms

2. SAFE   (opcode 131)  → enters Safe mode (recommended)
   Wait ≥ 50ms

Now you can send movement/sensor commands.
```

In bytes:

```python
ser.write(b'\x80')   # START
time.sleep(0.200)

ser.write(b'\x83')   # SAFE
time.sleep(0.050)
```

### Why Passive First?

Sending SAFE or FULL before START does nothing — the OI is not active yet.
START must always be the first OI command after wakeup.

---

## OI Modes

| Mode    | Opcode | Safety     | Use For                         |
|---------|--------|------------|----------------------------------|
| Passive | 128    | Full       | Starting up, cleaning cycles     |
| Safe    | 131    | Stops on cliff/bump | Normal robot operation  |
| Full    | 132    | NONE       | Testing only — will fall off edges |
| Off     | 173    | —          | Shutdown OI                      |

> **Recommendation:** Always run in **Safe mode** unless you're testing
> specific hardware behavior. Safe mode prevents the Roomba from driving
> off a table or cliff edge.

---

## DRIVE_DIRECT Command

This is the **preferred** movement command — it controls each wheel
independently with a specific velocity.

**Opcode:** 145 (0x91)
**Format:** `[145] [right_high] [right_low] [left_high] [left_low]`

- Velocities are **signed 16-bit integers**, **big-endian** (high byte first)
- Range: **-500 to +500 mm/s**
- Positive = forward, Negative = backward

### Examples

```python
import struct

def drive_direct(right_mm_s: int, left_mm_s: int) -> bytes:
    return bytes([145]) + struct.pack(">h", right_mm_s) + struct.pack(">h", left_mm_s)

# Drive straight forward at 200 mm/s
ser.write(drive_direct(200, 200))

# Spin clockwise (right wheel fwd, left wheel back)
ser.write(drive_direct(200, -200))

# Stop
ser.write(drive_direct(0, 0))
```

---

## Command Timing Requirements

The Roomba needs minimum delays between commands or it will ignore them:

| After this...          | Wait at least... |
|------------------------|------------------|
| Power on / wakeup      | 500ms            |
| START opcode           | 200ms            |
| Mode change (SAFE/FULL)| 50ms             |
| Between commands       | 15ms (use 30ms)  |

Violating these timings causes **silent command drops** — the Roomba gets
the byte but ignores it. This is one of the most common sources of confusion.

---

## Troubleshooting

### "No response to sensor queries"

1. **Check TX/RX wiring** — are they crossed? Roomba RXD → adapter TXD.
2. **Check baud rate** — try 115200, then 19200.
3. **Check wakeup** — did the Roomba beep when you pulsed RTS?
4. **Check permissions** — can you open the port?
   ```bash
   ls -la /dev/ttyUSB0
   groups $USER | grep dialout
   ```

### "Roomba doesn't move but sensor queries work"

1. Are you in SAFE or FULL mode? (check with sensor query 35)
2. Is the Roomba on carpet with the brushes spinning? (clean mode)
3. Is the battery charged? (sensor query 25, 26)

### "RTS wakeup doesn't work"

1. Try swapping: `setRTS(True)` ↔ `setRTS(False)`
2. Your adapter may label RTS differently — check adapter documentation
3. Try holding the **Clean button** on the Roomba for 2 seconds to force-wake it
4. Some cheap CH340 adapters don't expose RTS properly — use CP2102 or FTDI

### "Commands work once then stop"

- You're not sending `SAFE` after `START` — Passive mode ignores drive commands.
- Add the mode after wakeup.

### "Port not found after reboot"

- USB-serial adapters get new device numbers on each boot
- Use `by-id` path for consistency:
  ```bash
  ls /dev/serial/by-id/
  # Example: /dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A50285BI-if00-port0
  ```
- Set this path in `config/local_config.yaml`:
  ```yaml
  roomba:
    port: "/dev/serial/by-id/usb-FTDI_..."
  ```

---

## Diagnostic Commands

```bash
# List serial ports
ls /dev/ttyUSB*  /dev/ttyACM*

# Check who owns the port (must be in 'dialout' group)
ls -la /dev/ttyUSB0

# Add yourself to dialout (then log out + back in)
sudo usermod -aG dialout $USER

# Run full serial diagnostic
python diagnostics/check_roomba_serial.py

# Interactive Roomba test
python roomba/roomba_test.py
```
