from oakey import KeyListener
import queue

my_queue = queue.Queue()
listener = KeyListener(target_queue=my_queue)

print("Listener started. Press keys (or 'ctrl+c' to quit)...")
listener.start()

try:
    while True:
        # Blocking read from standard queue.Queue
        key = listener.get()
        print(f"Captured: {key}\r")  # \r used for clean raw line returns

        if key == "ctrl+c":
            print("Exiting...\r")
            break
finally:
    listener.stop()
