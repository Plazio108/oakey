import oakey

def log_error(err):
    print(f"Error captured: {err}\r")

# If target_queue is omitted, it auto-creates a queue.
# Use context manager for auto start/stop and clean terminal restore.
with oakey.KeyListener(on_error=log_error) as listener:
    q = listener.get_queue()  # Or listener.queue
    print("Listening... Press 'ctrl+c' to quit.\r")
    
    while True:
        key = listener.get()  # Direct queue wrapper
        print(f"Captured: {key}\r")
        if key == "ctrl+c":
            break
