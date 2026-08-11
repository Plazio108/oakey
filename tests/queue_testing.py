import queue
import oakey

my_existing_queue = queue.Queue()
listener = oakey.KeyListener(target_queue=my_existing_queue)

listener.start()

try:
    print(f"Queue empty? {listener.empty()}\r")
    
    while True:
        key = listener.get(block=True, timeout=5.0)
        print(f"Key: {key} | Current Queue Size: {listener.qsize()}\r")
        
        if key == "ctrl+c":
            listener.clear() # Clear any leftover key buffer
            break
finally:
    listener.stop()
