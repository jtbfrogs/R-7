# Debugging Guide

## Golden Rule: Isolate Systems

When something doesn't work, **test each system in isolation** before
assuming the whole stack is broken.

```
Problem → Run check_all.py → Run the specific check_*.py → Fix → Re-test
```

---

## Debug Mode

Every script supports `--debug` for verbose logging:

```bash
python main.py --debug
python roomba/roomba_test.py --debug
python commands/command_console.py --debug
```

Debug mode shows every byte sent to the Roomba, every detection result,
every AI query — everything.

---

## Roomba Doesn't Connect

**Step 1:** Check the port exists:
```bash
ls /dev/ttyUSB*
ls /dev/ttyACM*
```

**Step 2:** Check permissions:
```bash
ls -la /dev/ttyUSB0
groups $USER | grep dialout
```

If not in dialout: `sudo usermod -aG dialout $USER` then **log out and back in**.

**Step 3:** Run the serial diagnostic:
```bash
python diagnostics/check_roomba_serial.py
```

**Step 4:** Use the interactive tester with debug:
```bash
python roomba/roomba_test.py --debug --port /dev/ttyUSB0
> connect
> status
> mode
```

---

## Roomba Connects But Ignores Commands

**Most common cause:** Missing timing delays between commands.

Check that you're waiting 200ms after START and 50ms after mode changes.
The `RoombaController` handles this automatically — if you're calling opcodes
directly, add the delays.

**Second most common:** You're in Passive mode, not Safe/Full.
Run `mode` in the test console to check. If it says "1" (PASSIVE), send SAFE.

---

## Roomba Wakes Up But Movement Doesn't Work

Check sensor packet 35 (OI mode):
```bash
> mode     # in roomba_test.py
```
- If 0: OI is off — send START + SAFE
- If 1: Passive mode — send SAFE
- If 2: Safe mode ✓ — movement should work
- If 3: Full mode ✓ — movement should work

Also check that the battery is charged. Low battery = no movement.

---

## Camera Not Detected

```bash
ls /dev/video*
v4l2-ctl --list-devices   # requires v4l-utils
python diagnostics/check_camera.py
python diagnostics/check_camera.py --index 1   # try index 1
```

---

## Ollama AI Slow / Not Responding

```bash
# Check if Ollama is running
curl http://localhost:11434/api/tags

# Start Ollama
ollama serve

# Test the model
python diagnostics/check_ollama.py

# Try a smaller model
ollama pull tinyllama
```

---

## TTS Silent / Crashes

```bash
# Test espeak directly
espeak "hello"

# Run TTS diagnostic
python diagnostics/check_tts.py

# Install espeak if missing
sudo apt install espeak espeak-data libespeak1
```

---

## Reading Logs

All logs go to `logs/droid.log` (rotated at 5MB).

```bash
# Watch live logs
tail -f logs/droid.log

# Search for errors
grep ERROR logs/droid.log

# Search for a subsystem
grep "\[ROOMBA\]" logs/droid.log
grep "\[VISION\]" logs/droid.log
grep "\[AI\]" logs/droid.log
```

---

## Serial Port Changes on Reboot

Use the stable by-id path:
```bash
ls /dev/serial/by-id/
# Copy the path and put it in config/local_config.yaml:
```
```yaml
roomba:
  port: "/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_XXXXXXXX-if00-port0"
```
