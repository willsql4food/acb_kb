import threading, time, json
import concurrent.futures

# --------------------------------------------------------------------------------------------------------
def _runNotebook(params):
    """
    Private function to invoke a notebook given a nb_path and optional parameter list

    Parameters
    --------------------
    params : List of dict (key/value pairs):
        nb_path:    path and name of notebook to execute
        params:     parameters expected in the called notebook
        debug:      optional - if given, debug messaging is displayed
    
    Returns
    --------------------
        None
    """

    # params passed as a list, but should only have one element
    start = time.time()
    msg = f"\n**********************************************\nInvoking notebook: {params['nb_path']}"
    # Iterate parameters & values
    for k, v in params['params'].items():
        msg += f"\n\t{k} = {v}"

    # Override timeout_seconds if provided
    tos = 3600
    if 'timeout_seconds' in params:
        tos = params['timeout_seconds']
    msg += f"\n\ttimeout_seconds = {tos}"

    # To return a json object with data about the notebook run
    # Needs: Name of table/notebook, number of rows written, and maybe time taken
    notebook_string = params['dbutils'].notebook.run(path=params['nb_path'], timeout_seconds=tos, arguments=params['params'])

    fin = time.time()

    time_string = f"{fin - start:.2f} seconds"
    msg += f"\nNotebook finished: {time_string}"
    # Run the notebook as specified
    if 'debug' in params:
        print(msg)

    if notebook_string is not None and notebook_string != '':
         notebook_json = json.loads(notebook_string.replace("'", '"'))
         notebook_json["runTime"] = time_string
         return notebook_json
    else:
        return None
    


# --------------------------------------------------------------------------------------------------------
def runParallelNotebooks(dbutils, parameterStack, maxDoP=8, debug=False):
    """
    Runs multiple notebooks in parallel with throttling capability

    Parameters
    --------------------
    dbutils:        The instance of dbutils running on the caller

    parameterStack: List of dict (key/value pairs):
           nb_path: path and name of notebook to execute
            params: parameters expected in the called notebook

    maxDoP:         Maximum number of threads to be allowed to execute simultaneously

    debug:          Optional - if given, debug messaging is displayed

    Returns
    --------------------
        None
    """

    # A list to hold all the threads we start
    start = time.time()
    threads = []
    toDo = []
    for ps in parameterStack:
        toDo.append(ps)

    # For throttling, we're popping from the list until its empty
    startedThreads = 0

    # While there are tasks to do...
    while len(toDo) > 0:
        # ... and there are threads available
        while len(threads) < maxDoP:
            
            # If we've run out of things to do, break from this loop
            if len(toDo) == 0:
                if debug:
                    print(f"\n===\tAll {len(parameterStack)} tasks have been started\n")
                break
            
            # Get first available item and add dbutils parameter to it
            # (or overwrite if already present)
            ps = toDo.pop(0)
            ps['dbutils'] = dbutils
            
            # Add a debug message flag if requested
            if debug:
                ps['debug'] = True

            # Create a thread, providing the function to call and the parameter values to pass it (as a single list)
            t = threading.Thread(target=_runNotebook, args=[ps])
            startedThreads += 1

            # Add the thread to our list and start it
            threads.append(t)
            t.start()
            if debug:
                print(f"+++\t{len(threads)} running threads.  [{startedThreads} / {len(parameterStack)}]")

        # All threads in use - monitor for one to come free
        while len(threads) == maxDoP:
            for rt in threads:
                if not rt.is_alive():
                    threads.remove(rt)
                    if debug:
                        print(f"---\t{len(threads)} running threads.  [{startedThreads} / {len(parameterStack)}]")

    # Join the thread to the calling thread (this cell) 
    # so we stick around to get their finish state
    for t in threads:
        t.join()

    fin = time.time()
    if debug:
        print(f"\nParallel execution finished\n\t{fin - start:.2f} seconds.")


# ---------------------------------------------------------------------------------------------------------------------------
def runParallelNotebooksNew(dbutils, parameterStack, maxDoP=8, debug=False):
    """
    Runs multiple notebooks in parallel with throttling capability

    Parameters
    --------------------
    dbutils:        The instance of dbutils running on the caller

    parameterStack: List of dict (key/value pairs):
           nb_path: path and name of notebook to execute
            params: parameters expected in the called notebook

    maxDoP:         Maximum number of threads to be allowed to execute simultaneously

    debug:          Optional - if given, debug messaging is displayed

    Returns
    --------------------
    notebook_results:   json list of the results of each notebook containing a table name, rows written, and time taken to complete
    """
    
    notebook_results = []

    #Automatically schedules the threading jobs for each notebook based on the established max workers
    with concurrent.futures.ThreadPoolExecutor(maxDoP) as executor:
        futures = {executor.submit(_runNotebook, {**params, 'dbutils': dbutils}): params
               for params in parameterStack}
        
        #Appends the results of each notebook to the json list
        for future in concurrent.futures.as_completed(futures):
            try:
                notebook_results.append(future.result())
            except Exception as e:
                notebook_results.append({"error": str(e)})
    return notebook_results
