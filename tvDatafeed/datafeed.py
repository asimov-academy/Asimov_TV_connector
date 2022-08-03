###############################################################################
#
# Copyright (C) 2022-2023 Ron Freimann
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
###############################################################################

from tvDatafeed import TvDatafeed
from datetime import datetime as dt
from tvDatafeed.Seis import SeisManager
import threading, queue
import time

# TODO: replace teis with seis name
# TODO: create a separate class for teis_id extending the int class
# TODO: change the name tvDatafeedRealtime to tvDatafeedLive and add get_hist method which is thread safe and uses the same tvDatafeed instance

class ts_callback(): # TODO: replace getter and setter methods with simple attribute accessing
    """
    Contain information for identifying a callback thread
    
    Holds ticker set ID and queue_id which provide a way to identify a 
    specific callback thread. 
    
    Methods
    -------
    get_ts_id()
        Return ticker set ID
    set_ts_id(ts_id)
        Set ticker set ID
    get_queue_id()
        Return callback thread queue ID
    set_queue_id(queue_id)
        Set callback thread queue ID
    """
    def __init__(self, ts_id, queue_id):
        """
        Parameters
        ----------
        ts_id : int
            Ticker set ID
        queue_id : int
            Callback thread queue ID
        """
        self.ts_id=ts_id
        self.queue_id=queue_id
    
    def get_ts_id(self):
        """
        Return ticker set ID
        
        Returns
        -------
        int
            ticker set ID
        """
        return self.ts_id
    
    def set_ts_id(self, ts_id):
        """
        Set ticker set ID
        
        Parameters
        ----------
        ts_id: int
            ticker set ID
        """
        self.ts_id=ts_id
        
    def get_queue_id(self):
        """
        Return callback thread queue ID
        
        Returns
        -------
        int
            callback thread queue ID
        """
        return self.queue_id
    
    def set_queue_id(self, queue_id):
        """
        Set callback thread queue ID
        
        Parameters
        ----------
        queue_id : int
            callback thread queue ID
        """
        self.queue_id=queue_id

class tvDatafeedRealtime():
    """
    Retrieve live ticker data from TradingView.com
    
    Retrieve live ticker data from TradingView.com using the tvDatafeed 
    module. The user must add a ticker set (ticker, exchange and interval) 
    which will then be monitored in TradingView for updates. If the ticker 
    set has a new bar produced (for specified interval) then this bar will 
    be  retrieved (datetime, OHLCV). The user can register one or many 
    callback functions for each ticker set which will be called one-by-one 
    once the new bar is retrieved. Ticker data retrieving and callback
    functions execution will run in separate threads to ensure near 
    real time operation and non-blocking if any of the callback functions
    is blocking.
    
    Methods
    -------
    add_ticker_set(symbol, exchange, interval, timeout=-1)
        Adds new ticker for which new bar data will be retrieved
    del_ticker_set(seis_id, timeout=-1)
        Remove ticker set from the list of tickers to be monitored for updates
    add_callback(seis_id, callback_func, timeout=-1)
        Create a callback thread for ticker set ID
    del_callback(seis_queue_pair, timeout=-1)
        Stop and shutdown a callback thread
    stop()
        Shutdown main thread and all the callback threads
    """
    def __init__(self, unique_seis_id=True, username=None, password=None, chromedriver_path=None, auto_login=True):
        """
        Parameters
        ----------
        unique_ts_id : boolean, optional
            Generated ticker set ID integers are unique or not (default True)
        username : str, optional
            TradingView username (default None)
        password : str, optional
            TradingView password (default None)
        chromedriver_path : str, optional
            path to chromedriver on local machine (default None)
        auto_login : boolean, optional
            specify if system tries to login or uses public TradingView 
            interface (default True)
        """
        self._sm=SeisManager(unique_seis_id)
        self._tv_datafeed = TvDatafeed(username=username, password=password, chromedriver_path=chromedriver_path, auto_login=auto_login) 
        self._timeout_datetime = None # this specifies the time waited until next sample(s) are retrieved from tradingView 
        
        self._callback_threads = {} # this holds reference to all the callback threads running, key values will be queue object references
        self._main_thread = None # this variable is used for referencing the main thread running collect_data_loop
        self._interrupt=threading.Event() # this will be used to close the collect_data_loop thread
        self._interrupt.shutdown=False # by default the interrupt reason is not shutdown
        
    def add_symbol(self, symbol, exchange, interval, timeout=-1):
        """
        Adds new ticker for which new bar data will be retrieved
        
        Adds a ticker set (ticker, exchange, updating time interval) into list
        of tickers which will be monitored on TradingView. If that ticker has
        a new bar produced on TradingView then that will be retrieved and 
        callback functions associated with this ticker set will be called.
        Method will return an integer called ticker set ID - this number will
        be unique among all other ticker set ID numbers (existing and removed) 
        if 'unique_ts_id' option was 'True' when instantiating the class. 
        Otherwise this number can be re-used if this ticker set is removed 
        (with 'del_ticker_set' method) and a new ticker set is added. This
        method might not execute right away because it is waiting for some
        internal resources to become available - the user can provide a
        optional timeout argument if needed.
        
        Parameters
        ----------
        symbol : str
            ticker used in the exchange from which data will be retrieved
        exchange : str
            exchange or market from where to retrieve data in TradingView
        interval : Interval
            updating time interval for the ticker
        timeout : int, optional
            time to wait before timing out and returning from this method without
            completion, value -1 (default) means there is no timeout
            
        Returns
        -------
        int
            unique number to identify this ticker set (ticker, exchange, 
            interval)
        """
        self._sm.get_lock(timeout)
        seis_id=self._sm.add_seis(symbol, exchange, interval)
        in_list=self._sm.get_timeframe(interval) # get the next update time for this interval
        if in_list is None: # None if we are not monitoring this interval yet
            data=self._tv_datafeed.get_hist(symbol,exchange,n_bars=2,interval=interval) # get data for this symbol and interval
            self._sm.add_timeframe(interval, data.index.to_pydatetime()[0]) # add this datetime into list of timeframes we monitor; to_pydatetime converts into list of datetime objects
            
            # check if new _timeout_datetime value would be shorter than the current one that we might be waiting upon
            if self._timeout_datetime is None:
                pass # we don't have any timeout yet so simply do nothing
            elif self._timeout_datetime > self._sm.get_trigger_dt(): # if new timeout would be sooner
                self._interrupt.set() # interrupt the waiting to set the new timeout value for waiting statement
        
        self._sm.drop_lock() 
        
        if self._main_thread is None: # if main thread is not running then start (might have not yet started or might have closed when all seises were removed)
            self._interrupt.shutdown=False
            self._interrupt.clear() # reset shutdown flag, don't need lock because nothing is running at this point
            self._main_thread = threading.Thread(target=self.__collect_data_loop, args=(self._interrupt,))
            self._main_thread.start() 
        
        return seis_id
    
    def del_symbol(self, seis_id, timeout=-1):
        """
        Remove ticker set from the list of tickers to be monitored for updates
        
        Stop retrieving data for this ticker set and remove it from the list of
        tickers to be monitored for updates. Any callback threads registered 
        with this ticker set will be closed down. If there are no more ticker
        sets under monitor (empty) then ticker data retrieving (main) thread 
        will be closed down. This method might not execute right away because 
        it is waiting for some internal resources to become available - the 
        user can provide a optional timeout argument if needed.
        
        ts_id : integer
            unique identifier to reference ticker set (ticker, exchange, 
            interval)
        timeout : int, optional
            time to wait before timing out and returning from this method without
            completion, value -1 (default) means there is no timeout  
        
        Returns
        -------
        int
            if ticker set was successfully removed, if no such ticker set
            then None will be returned
        """
        self._sm.get_lock(timeout)
        seis=self._sm.get_seis(seis_id)
        if seis is None: # this seis does not exist anymore or has been deleted
            self._sm.drop_lock()
            return None
        for queue in seis.get_queues(): # remove and close all associated callback threads and their references
            self._callback_threads.pop(queue) # remove the callback thread reference from the dictionary
            queue.put(None) # send exit signal to thread
        self._sm.del_seis(seis_id) # delete the seis itself
        if self._sm.is_empty():
            self._interrupt.shutdown=True
            self._interrupt.set() # signal the __collect_data and main loop that they should close
        self._sm.drop_lock()
        
        return seis_id
        
    def __collect_data(self, interrupt):
        # Wait and collect new ticker data
        #
        # Internal method to wait until next timeframe(s) under monitor have new 
        # ticker data available. Each timeframe has a datetime when new data 
        # will be available. These datetimes for each timeframe are updated 
        # once they expire. When any timeframe(s) expire then new data will 
        # be retrieved for all the associated tickers. Multiple timeframes can 
        # produce data at the same time (eg. 1m and 5m). New data will be fed
        # into associated callback threads for associated tickers. Waiting can
        # be interrupted using the interrupt event. Interruption might occur
        # if the user wants to shut-down all or if there is new timeframe added
        # and we need to update the wait_time to take that into account.  
        # 
        # Parameters
        # ----------
        # interrupt : threading.Event
        #    if set without setting corresponding shutdown attribute then waiting 
        #    will be interrupted and all updating logic run and event cleared, if 
        #    shutdown attribute is set then method will interrupt and return with
        #    False
        #    
        # Returns
        # -------
        # boolean
        #    True if method ran without shutdown interrupt event, False if 
        #    shutdown event happened
        
        if self._timeout_datetime is not None: # first time there is no timeout datetime set, so skip this to get one
            wait_time=self._timeout_datetime-dt.now() # calculate the time in seconds to next timeout
            if interrupt.wait(wait_time.total_seconds()) and interrupt.shutdown: # if we received a shutdown event during waiting
                #raise RuntimeError() # raise an exception so we'll exit the while loop and close the thread; TODO: replace exception with return values
                return False
                
        self._sm.get_lock() 
        updated_timeframes=self._sm.get_expired_intervals() # returns a list of booleans for all intervals that we monitor
        self._timeout_datetime=self._sm.get_trigger_dt() # get datetime when next sample should becomes available (wait time)
        
        for inter in updated_timeframes:
            for seis in self._sm.get_grouped_seises(inter): # go through all the seises in this interval group 
                retry_counter=0 # keep track of how many tries so we give up at some point
                while True:
                    data=self._tv_datafeed.get_hist(seis.symbol,seis.exchange,n_bars=2,interval=seis.interval) # get the latest data bar for this seis
                    if data is None:
                        raise ValueError("Retrieved None from tvDatafeed get_hist method")
                    data=data.drop(labels=data.index[1], axis=0) # drop the row which has un-closed bar data
                    
                    # retrieved data datetime not equal the old datetime means new sample
                    if seis.updated != data.index.to_pydatetime()[0]:
                        seis.updated=data.index.to_pydatetime()[0] # update the datetime of the last sample
                        break
                    elif retry_counter >= 50: # we did not get new sample, try again up to 50 times
                        raise ValueError("Failed to retrieve new data from TradingView")
                    
                    time.sleep(0.1) # little time before retrying
                    retry_counter+=1
                    
                    if interrupt.is_set() and interrupt.shutdown: # check if shutdown has been signaled 
                        #raise RuntimeError() # raise an exception so we'll exit the while loop and close the thread; TODO: remove this line
                        self._sm.drop_lock() 
                        return False
                        
                # put this new data into all the queues for all the callback function threads that are expecting this data sample
                for queue in seis.get_queues():
                    queue.put(data)
        
        interrupt.clear() # in case we were interrupted, but not to shutdown then we can reset this event for next loop
        self._sm.drop_lock() 
        
        return True
    
    def __callback_thread(self, callback_function, queue, seis_id):
        # Get new ticker data and execute callback with this
        #
        # Retrieve new ticker data from the internal queue and call the provided
        # callback function with this data and ticker set ID. This method will 
        # run in a thread and will exit only once a None object is received.
        #
        # Parameters
        # ----------
        # callback_function : function
        #    function to be called with received data
        # queue : queue.Queue
        #    queue from where the new data will be read
        # ts_id : int
        #    ticker set ID that will be provided to callback function
        while True:
            data=queue.get() # this blocks until we get new data sample
            if data is None: # None is exit signal
                break # stop looping and close the thread
            
            callback_function((seis_id, data)) # call the function with tuple containing seis_id and ticker data
    
    def add_callback(self, seis_id, callback_func, timeout=-1):
        '''
        Create a callback thread for ticker set ID
        
        Method to add a function that will be called when new data sample
        (candlebar) becomes available for the specified ticker set 
        (symbol, exchange, interval). One seis can have multiple 
        callback functions attached to it and they will be called in
        separate threads. Might not execute right away because 
        it is waiting for some internal resources to become available - the 
        user can provide a optional timeout argument if needed. The callback 
        function must accept a tuple which will contain two elements - 
        ticker set id and data.
        
        Parameters
        ----------
        ts_id : int
            ticker set ID which is returned by the add_ticker_set() method
        callback_func : function
            function to be called
        timeout : int, optional
            time to wait before timing out and returning from this method without
            completion, value -1 (default) means there is no timeout  
            
        Returns
        -------
        ts_callback
            object which has two attributes - ticker set ID and queue ID and
            get-set methods to read them
        '''
        q=queue.Queue() # create a queue for this seis callback thread
        
        self._sm.get_lock(timeout) 
        queue_id=self._sm.add_queue(seis_id, q) # save a reference for this queue with this specific seis
        self._sm.drop_lock() 
        
        t=threading.Thread(target=self.__callback_thread, args=(callback_func, q, seis_id)) # create a thread running callback_thread function      
        self._callback_threads[q]=t  # use queue object reference to track callback threads because they are mapped 1-to-1; this way we hide thread reference from user
        t.start() # start callback function thread 
        
        return ts_callback(seis_id, queue_id)
        # return [asset_id, queue_id] # return a list containing asset_id, queue_id and reference to thread calling the callback function; TODO: rmeove this line
    
    def del_callback(self, callback_ref, timeout=-1):
        '''
        Stop and shutdown a callback thread
        
        Stop the callback thread. Method will remove the queue from the ticker
        set so __collect_data method will not send it to this thread anymore.
        
        Parameters
        ----------
        callback_ref : ts_callback
            object that contains ts_id and queue_id
        timeout : int, optional
            time to wait before timing out and returning from this method without
            completion, value -1 (default) means there is no timeout
            
        Returns
        -------
        ts_callback
            return the same callback reference if successful, return None if the
            specified callback thread does not exist anymore
        '''
        self._sm.get_lock(timeout)
        q=self._sm.get_queue(callback_ref.get_ts_id(), callback_ref.get_queue_id()) # get the actual queue instance ref before deleting it; TODO: del_queue method returns a queue object when deleting it, we do not need to use get method explicitly
        if q is None: # if no such seis 
            self._sm.drop_lock() # everything already done - thread is closed and reference is removed form the list
            return None
        self._sm.del_queue(callback_ref.get_ts_id(), callback_ref.get_queue_id()) # remove this queue from that seises list so no more data is sent to that queue
        self._sm.drop_lock() 
        q.put(None) # send the exit signal to that thread
        self._callback_threads.pop(q) # remove the thread reference from the dictionary
        
        return callback_ref
        
    def __collect_data_loop(self, interrupt):
        # Main thread function to return ticker data
        #
        # Retrieve ticker data in an infinite while loop. This method calls
        # __collect_data method and checks for the return value to detect if
        # shutdown is requested. In shutdown case it will send a close signal to
        # all the callback threads and then stop executing.
        #
        # Parameters
        # ----------
        # interrupt : threading.Event
        #    interrupt signal propagated to __collect_data method 
        try:
            while self.__collect_data(interrupt): # False will be returned if shutdown started
                pass
        finally:
            if self._sm.is_locked():
                self._sm.drop_lock() # in case it was not released
            # send a close signal to all the callback threads
            for seis in self._sm.get_seis_list():
                for queue in seis.get_queues():
                    queue.put(None) 
            
            self._main_thread = None
        
    def __del__(self):
        self._sm.get_lock() # need to get lock first because interrupt_flag (_shutdown) is accessed by many threads
        self._interrupt.shutdown=True
        self._interrupt.set()
        self._sm.drop_lock()
        if self._main_thread is not None:
            self._main_thread.join() # wait until all threads are closed down
    
    def stop(self):
        '''
        Shutdown main thread and all the callback threads
        
        Method is for shutting down the main thread and all the callback 
        threads. Should be called when shutting down the entire application.
        Method calls destructor method. 
        '''
        if self._main_thread is not None:
            self.__del__()  
        