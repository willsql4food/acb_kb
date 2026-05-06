import concurrent.futures
import time

def task(n):
    """A sample task that returns n / 10."""
    time.sleep(n % 3)
    if n == 4:
         raise Exception("Busted!")
    else:
	    return n / 10

def done_callback(future):
    """Callback function to process the completed future."""
    if future.cancelled():
        print(f"Future was cancelled.")
    elif future.exception():
        error = future.exception()
        print(f"Future raised an exception: {error}")
    else:
        result = future.result()
        print(f"Future returned result: {result}")

print('Main thread begins\n......................')

# Create an executor and submit a task
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
    fs = {executor.submit(task, i): i for i in range(1,11)}
    
# for future in concurrent.futures.as_completed(fs):
for future in fs:
	# Attach the callback
	future.add_done_callback(done_callback)

	time.sleep(1)

for future in fs:
	future.cancel()
	
print('......................\nMain thread ends')
