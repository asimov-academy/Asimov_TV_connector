import threading, queue, time

import tvDatafeed # circular import error so import entire package
from datetime import datetime as dt
from dateutil.relativedelta import relativedelta as rd
from dataclasses import dataclass

class TvDatafeedLive():
    """                 
    Retrieve historic and live ticker data from TradingView
    
    The user must add TODO: update this description part
    symbol-exchange-intervals set (seis) which defines a specific data 
    feed in TradingView.com and for which the updates will be retrieved. 
    If the set has a new bar available then datetime and OHLCV values for 
    this bar will be  retrieved and passed to consumers of that seis.
    The consumers are callback functions registered with this seis that
    will with bar data as input parameter. The user can register one or many 
    callback functions for each seis which will be called one-by-one 
    once the new bar is retrieved. Bar data retrieving and callback
    functions execution run in separate threads to ensure callback functions
    do not block the datafeed.
    
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
    
    class _SeisesAndTrigger(dict):
        '''
        Group Seises and manage interval expiry datetimes
        '''
        def __init__(self):
            super().__init__()
            
            self._trigger_quit=False
            self._trigger_dt=None
            self._trigger_interrupt=threading.Event()
            
            # time periods available in TradingView 
            self._timeframes={"1":rd(minutes=1), "3":rd(minutes=3), "5":rd(minutes=5), \
                             "15":rd(minutes=15), "30":rd(minutes=30), "45":rd(minutes=45), \
                             "1H":rd(hours=1), "2H":rd(hours=2), "3H":rd(hours=3), "4H":rd(hours=4), \
                             "1D":rd(days=1), "1W":rd(weeks=1), "1M":rd(months=1)}
        
        def _next_trigger_dt(self):
            '''
            Get the next closest expiry datetime
            '''
            if not self.values(): # if Seis list is empty
                return None
            
            interval_dt_list=[]
            for values in self.values():
                interval_dt_list.append(values[1])
            
            interval_dt_list.sort()

            return interval_dt_list[0]
        
        def wait(self):
            '''
            Wait until next interval(s) expire
            
            Returns true after waiting, even if interrupted. Returns False only
            when interrupted for shutdown
            '''
            self._trigger_dt=self._next_trigger_dt() # get new expiry datetime
            self._trigger_interrupt.clear() # in case it was set by refresh when not waiting
            
            while True: # might need to restart waiting if trigger_dt changes and interrupted when waiting
                wait_time=self._trigger_dt-dt.now() # calculate the time to next expiry
                
                if (interrupted := self._trigger_interrupt.wait(wait_time.total_seconds())) and self._trigger_quit: # if we received a shutdown event during waiting
                    return False 
                elif not interrupted: # if not interrupted then no more waiting needed
                    self._trigger_interrupt.clear() # in case waiting was interrupted, but not quit - reset the event flag
                    break

            return True
            
        def get_expired(self):
            '''
            Return expired intervals and update their expiry values
            '''
            expired_intervals=[]
            for interval, values in self.items():
                if dt.now() >= values[1]:
                    expired_intervals.append(interval)
                    values[1]= values[1] + self._timeframes[interval] # add interval to get new expiry dt in future
            
            return expired_intervals
        
        def quit(self):
            '''
            Interrupt wiating and return False - breaks the loop
            '''
            self._trigger_quit=True
            self._trigger_interrupt.set()
        
        def clear(self):
            '''
            Clear the list of interval groups and Seises
            '''
            raise NotImplementedError
        
        def append(self, seis, update_dt=None):
            '''
            Append new Seis instance into list
            '''
            if self: # if empty then reset flags
                self._trigger_quit=False
                self._trigger_interrupt.clear()
                
            if seis.interval.value in self.keys(): # interval group already exists
                super().__getitem__(seis.interval.value)[0].append(seis)
            else: # new interval group needs to be created
                if update_dt is None:
                    raise ValueError("Missing update datetime for new interval group")
                else:
                    update_dt= update_dt + self._timeframes[seis.interval.value] # change the time to next update datetime (result will be datetime object)
                    self.__setitem__(seis.interval.value, [[seis], update_dt]) 
                    
                    if (trigger_dt := self._next_trigger_dt()) != self._trigger_dt: # if new interval group expiry is sooner than current expiry being waited on
                        self._trigger_dt=trigger_dt
                        self._trigger_interrupt.set()
           
        def discard(self, seis):
            '''
            Remove Seis instance from the list
            '''
            if seis not in self:
                raise KeyError("No such Seis in the list")
            else:
                super().__getitem__(seis.interval.value)[0].remove(seis)
                if not super().__getitem__(seis.interval.value)[0]: # if interval group now empty then remove it
                    self.pop(seis.interval.value)    
                    
                    if ((trigger_dt := self._next_trigger_dt()) != self._trigger_dt) and (self._trigger_quit is False): # if interval group expiry dt was being waited on and havent quit
                        self._trigger_dt=trigger_dt
                        self._trigger_interrupt.set()
            
        def intervals(self):
            '''
            Return list of interval groups
            '''
            return self.keys()
        
        def __getitem__(self, interval_key):
            return super().__getitem__(interval_key)[0]
        
        def __iter__(self):
            seises_list=[]
            
            for seis_list in super().values():
                seises_list+=seis_list[0]
            
            return seises_list.__iter__()
        
        def __contains__(self, seis):
            for seis_list in super().values():
                if seis in seis_list[0]:
                    return True
            
            return False
    
    def __init__(self, username=None, password=None, chromedriver_path=None, auto_login=True):
        """
        Parameters
        ----------
        unique_seises : boolean, optional
            Generated symbol-exchange-interval set ID integers are unique 
            (default True)
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
        self._lock=threading.Lock()
        self._main_thread = None 
        self._tv_datafeed = tvDatafeed.TvDatafeed(username=username, password=password, chromedriver_path=chromedriver_path, auto_login=auto_login) # TODO: use inheritance from tvDatafeed instead of creating instance of this class inside this class 
        self._sat = self._SeisesAndTrigger() 
    
    def add_seis(self, *args, timeout=-1):
        '''
        Add new Seis to tvDatafeed SAT list
        '''
        # check if symbol, exchange and Interval arguments or Seis argument provided as input
        if len(args) == 3:
            new_seis=tvDatafeed.Seis(args[0], args[1], args[2])
        elif len(args) == 1:
            new_seis=args[0]
        else:
            raise TypeError("Wrong number of arguments provided or missing parameters")
        
        self._lock.acquire(timeout=timeout)
        new_seis.tvdatafeed=self
        
        # if this seis is already in list 
        if new_seis in self._sat:
            raise self.ValueError("Duplicates not allowed")
        
        # add to interval group - if interval group does not exists then create one
        interval_key=new_seis.interval.value
        if interval_key not in self._sat.intervals():
            # get last bar update datetime value for the Seis
            ticker_data=self._tv_datafeed.get_hist(new_seis.symbol, new_seis.exchange, new_seis.interval, n_bars=1) # get single ticker data bar for this symbol from TradingView
            update_dt=ticker_data.index.to_pydatetime()[0] # extract datetime of when this bar was produced/released
            # append this seis into SAT
            self._sat.append(new_seis, update_dt)
        else:
            self._sat.append(new_seis)
        
        self._lock.release()
        
        if self._main_thread is None: # if main thread is not running then start 
            self._main_thread = threading.Thread(target=self._main_loop)
            self._main_thread.start() 
        
        return new_seis
        
    def del_seis(self, seis, timeout=-1):
        if seis not in self._sat:
            raise ValueError("Seis is not listed in SAT")
        
        self._lock.acquire(timeout=timeout)
        # close all the callback threads for this Seis
        for consumer in seis.get_consumers():
            consumer.put(None) # None signals closing for the callback thread
                
        # remove Seis from MAR list
        self._sat.discard(seis)
        del seis.tvdatafeed
        
        # if SAT list empty now then close down main loop
        if not self._sat:
            self._sat.quit()
        
        self._lock.release()
    
    def new_consumer(self, seis, callback, timeout=-1):
        '''
        Create a new Consumer for this seis with provided callback
        '''
        if seis not in self._sat:
            raise ValueError("Seis is not listed in SAT")
        
        # new consumer to hold callback related info
        # TODO: check here that input Seis has reference to this tvdatafeed
        consumer=tvDatafeed.Consumer(seis, callback) 
        self._lock.acquire(timeout=timeout)
        seis.add_consumer(consumer)     
        consumer.start()  
        self._lock.release()
        
        return consumer 
    
    def del_consumer(self, consumer, timeout=-1): # NEW METHOD
        '''
        Shutdown callback thread and remove the consumer from Seis
        '''
        self._lock.acquire(timeout=timeout)
        consumer.seis.pop_consumer(consumer)
        consumer.stop()
        self._lock.release()
        
    def _main_loop(self):
        # Main thread function to return ticker data
        #
        # Retrieve ticker data in an infinite while loop. This method calls
        # _collect_data method and checks for the return value to detect if
        # shutdown is requested. In shutdown case it will send a close signal to
        # all the callback threads and then stop executing.
        #
        # Parameters
        # ----------
        # interrupt : threading.Event
        #    interrupt signal propagated to __collect_data method 
        
        while self._sat.wait(): # waits until soonest expiry and returns True; returns False if closed                     
            self._lock.acquire() # TODO: use context manager instead of manually locking and releasing
            
            for interval in self._sat.get_expired(): # returns a list of intervals that have expired
                for seis in self._sat[interval]: # go through all the seises in this interval group 
                    for retry_count in range(0,50): # re-try maximum of RETRY_LIMIT times; TODO: turn this number into parameter set from conf file
                        data=self._tv_datafeed.get_hist(seis.symbol, seis.exchange, interval=seis.interval, n_bars=2)
                        data=data.drop(labels=data.index[1], axis=0) # drop the row which has un-closed bar data (index 1)
                        
                        # retrieved data datetime not equal the old datetime means new sample
                        if seis.updated != data.index.to_pydatetime()[0]: # TODO: create a method in Seis class called is_new_data(data) in which we do datetime checking
                            seis.updated=data.index.to_pydatetime()[0] # update the datetime of the last sample
                            break
                        elif retry_count == 49: # limit reached, throw an exception (RETRY_LIMIT-1)
                            raise ValueError("Failed to retrieve new data from TradingView")
                        
                        time.sleep(0.1) # little time before retrying
                        
                    # push new data into all consumers that are expecting data for this Seis
                    for consumer in seis.get_consumers():
                        consumer.put(data)
            
            self._lock.release()
        
        # send a shutdown signal to all the callback threads
        self._lock.acquire()
        
        for seis in self._sat:
            for consumer in seis.get_consumers():
                seis.pop_consumer(consumer)
                consumer.stop()
            
            self._sat.discard(seis)
            
        self._main_thread = None
        
        self._lock.release()
        
    def __del__(self):
        self._lock.acquire()
        self._sat.quit() #shutdown the main_loop
        self._lock.release()
        
        # wait until all threads are closed down - they are closed in the main_loop
        if self._main_thread is not None:
            self._main_thread.join() 
    
    def stop(self): # TODO: change this method to del_tvdatafeed() and in this after stopping the threads dereference everything
        '''
        Shutdown main thread and all the callback threads
        
        Method is for shutting down the main thread and all the callback 
        threads. Should be called when shutting down the entire application.
        Method calls destructor method. 
        '''
        if self._main_thread is not None:
            self.__del__()  
        