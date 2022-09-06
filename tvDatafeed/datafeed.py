import threading, queue, time
import tvDatafeed 
from datetime import datetime as dt
from dateutil.relativedelta import relativedelta as rd

RETRY_LIMIT=50 # max number of retries to get valid data from tvDatafeed; TODO: think about creating a conf file for such parameters

class TvDatafeedLive(tvDatafeed.TvDatafeed):
    """                 
    Retrieve historic and live ticker data from TradingView.
    
    User can add multiple symbol-exchange-interval sets (called Seis)
    to live feed monitoring list. For each Seis the user can add one
    or multiple callback functions (Consumers). Monitoring means that 
    once any of those symbols have a new data bar available in 
    TradingView then those bars will be retrieve and passed as an 
    argument to the each callback function registered for that Seis.
    The user can also collect historic data either while live feed
    is running or not.
    
    Parameters
    ----------
    username : str, optional
        TradingView username (default None)
    password : str, optional
        TradingView password (default None)
    
    Methods
    -------
    new_seis(symbol, exchange, interval, timeout)
        Create and add new Seis to live feed
    del_seis(seis, timeout)
        Remove Seis from live feed
    new_consumer(seis, callback, timeout)
        Create a new consumer for Seis with provided callback
    del_consumer(consumer, timeout)
        Remove the consumer from Seis consumers list
    get_hist(symbol, exchange, interval, n_bars, fut_contract, extended_session, timeout)
        Get histroic ticker data
    del_tvdatafeed
        Stop and delete this object
    """
    
    class _SeisesAndTrigger(dict):
        # Internal class to contain an array of Seis objects
        # and to manage/track their interval update times
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
            # Get the next closest expiry datetime
            if not self.values(): # if Seis list is empty
                return None
            
            interval_dt_list=[]
            for values in self.values():
                interval_dt_list.append(values[1])
            
            interval_dt_list.sort()

            return interval_dt_list[0]
        
        def wait(self):
            # Wait until next interval(s) expire
            # returns true after waiting, even if interrupted. Returns False only
            # when interrupted for shutdown
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
            # return expired intervals in a list, update expiry values
            expired_intervals=[]
            for interval, values in self.items():
                if dt.now() >= values[1]:
                    expired_intervals.append(interval)
                    values[1]= values[1] + self._timeframes[interval] # add interval to get new expiry dt in future
            
            return expired_intervals
        
        def quit(self):
            # interrupt waiting and return False - breaks the loop
            self._trigger_quit=True
            self._trigger_interrupt.set()
        
        def clear(self):
            # clear the list of interval groups and Seises
            raise NotImplementedError
        
        def append(self, seis, update_dt=None):
            # append new Seis instance into list
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
            # remove Seis instance from the list
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
            # return list of interval groups
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
    
    def __init__(self, username=None, password=None):
        super().__init__(username, password)
        
        self._lock=threading.Lock()
        self._main_thread = None  
        self._sat = self._SeisesAndTrigger() 
    
    def new_seis(self, symbol, exchange, interval, timeout=-1): 
        '''
        Create and add new Seis to live feed
        
        The user must provide symbol, exchange and interval 
        values based on which a new Seis instance will be 
        created and added into live feed.
        Timeout value can be used to specify maximum wait time
        for the method to return.
        
        Parameters
        ----------
        symbol : str 
            ticker string for symbol
        exchange : str
            exchange where symbol is listed
        interval : tvDatafeed.Interval
            chart interval
        
        timeout : int, optional
            maximum time to wait in seconds for return, default
            is -1 (blocking)
            
        Returns
        ----------
        Seis
            created based on the provided symbol, exchange 
            and interval values.
        
        Raises
        ----------
        ValueError
            If Seis with such symbol-exchange-interval 
            combination already exists.
        '''
        new_seis=tvDatafeed.Seis(symbol, exchange, interval)
        
        self._lock.acquire(timeout=timeout)
        new_seis.tvdatafeed=self
        
        # if this seis is already in list 
        if new_seis in self._sat:
            raise self.ValueError("Duplicates not allowed") # TODO make it so instead of exception the existing Seis object is returned
        
        # add to interval group - if interval group does not exists then create one
        interval_key=new_seis.interval.value
        if interval_key not in self._sat.intervals():
            # get last bar update datetime value for the Seis
            ticker_data=super().get_hist(new_seis.symbol, new_seis.exchange, new_seis.interval, n_bars=2) # get ticker data bar for this symbol from TradingView
            update_dt=ticker_data.index.to_pydatetime()[1] # extract datetime of when this bar was produced/released
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
        '''
        Remove Seis from live feed
        
        Parameters
        ----------
        seis : Seis
            Seis object to be removed
        timeout : int, optional
            maximum time to wait in seconds for return, default
            is -1 (blocking)
            
        Raises
        ----------
        ValueError
            If Seis does not exist in live feed (has not been added)
        '''
        if seis not in self._sat:
            raise ValueError("Seis is not listed")
        
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
        Create a new Consumer for this Seis with provided callback
        
        Parameters
        ----------
        seis : Seis
            Seis object for which the Consumer object is created
        callback : func
            Callback function to be called when Seis has new data
        timeout : int, optional
            maximum time to wait in seconds for return, default
            is -1 (blocking)
        
        Returns
        ----------
        Consumer
            Contains reference to provided Seis and callback function
            
        Raises
        ----------
        ValueError
            If Seis does not exist in live feed (has not been added)
        '''
        if seis not in self._sat:
            raise ValueError("Seis is not listed")
        
        # new consumer to hold callback related info
        consumer=tvDatafeed.Consumer(seis, callback)
        self._lock.acquire(timeout=timeout)
        seis.add_consumer(consumer)     
        consumer.start()  
        self._lock.release()
        
        return consumer 
    
    def del_consumer(self, consumer, timeout=-1): 
        '''
        Remove the consumer from Seis consumers list
        
        Parameters
        ----------
        consumer : Consumer
            Consumer to be removed
        timeout : int, optional
            maximum time to wait in seconds for return, default
            is -1 (blocking)
        '''
        self._lock.acquire(timeout=timeout)
        consumer.seis.pop_consumer(consumer)
        consumer.stop()
        self._lock.release()
        
    def _main_loop(self):
        # Main thread to return ticker data
        #
        # Retrieve symbol data in an infinite while loop. The while
        # loop expression will wait until next symbol that is 
        # monitored for will have new data available and return True.
        # If the user removes all Seises or calls del_tvdatafeed() 
        # then waiting will be interupted and returns False in which
        # case first all the consumer threads are closed and then this 
        # main thread is closed. Once wait() method returns then we
        # get a list of intervals which were under monitor and have 
        # expired. We loop through every Seis which has that 
        # interval and retrieve new data and push it into all the 
        # consumer threads that are added for that particular Seis.
        #
        # If fail to retrieve data then retry up to RETRY_LIMIT times 
        # and if still fail then raise ValueError.
        
        while self._sat.wait(): # waits until soonest expiry and returns True; returns False if closed                     
            self._lock.acquire() # TODO: use context manager instead of manually locking and releasing
            
            for interval in self._sat.get_expired(): # returns a list of intervals that have expired
                for seis in self._sat[interval]: # go through all the seises in this interval group 
                    for _ in range(0, RETRY_LIMIT): # re-try maximum of RETRY_LIMIT times
                        data=super().get_hist(seis.symbol, seis.exchange, interval=seis.interval, n_bars=2) # get_hist returns bars starting with currently open so need to read 2 to get first closed
                        if data is not None:
                            # retrieved data datetime not equal the old datetime means new sample
                            if seis.updated != data.index.to_pydatetime()[0]: # TODO: create a method in Seis class called is_new_data(data) in which we do datetime checking
                                seis.updated=data.index.to_pydatetime()[0] # update the datetime of the last sample
                                data=data.drop(labels=data.index[1]) # drop the row which has un-closed bar data
                                break
                        
                        time.sleep(0.1) # little time before retrying
                    else: # limit reached, throw an exception (RETRY_LIMIT-1)
                        raise ValueError("Failed to retrieve new data from TradingView") # TODO: use correct exception; maybe use logging instead of exceptions?
                    
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
    
    # TODO: make it possible for the user to provide arguments in either Seis or original format
    def get_hist(self,  
        symbol: str,
        exchange: str = "NSE",
        interval: tvDatafeed.Interval = tvDatafeed.Interval.in_daily,
        n_bars: int = 10,
        fut_contract: int = None,
        extended_session: bool = False,
        timeout=-1,
    ): 
        '''
        Get historical data
        
        Parameters
        ----------
        symbol : str
            symbol name
        exchange : str, optional 
            exchange, not required if symbol is in format 
            EXCHANGE:SYMBOL. Defaults to None.
        interval : tvDatafeed.Interval, optional
            chart interval. Defaults to Interval.in_daily
        n_bars : int, optional
            no of bars to download, max 5000. Defaults to 10.
        fut_contract : int, optional
            None for cash, 1 for continuous current contract in front,
            2 for continuous next contract in front. Defaults to None.
        extended_session : bool, optional 
            regular session if False, extended session if True, 
            Defaults to False.

        Returns
        -------
        pd.Dataframe
            dataframe with sohlcv as columns
        '''
        self._lock.acquire(timeout=timeout)
        data=super().get_hist(symbol, exchange, interval, n_bars, fut_contract, extended_session)
        self._lock.release()
        
        return data
       
    def __del__(self):
        self._lock.acquire()
        self._sat.quit() #shutdown the main_loop
        self._lock.release()
        
        # wait until all threads are closed down - they are closed in the main_loop
        if self._main_thread is not None:
            self._main_thread.join() 
    
    def del_tvdatafeed(self): 
        '''
        Stop and delete this object
        '''
        if self._main_thread is not None:
            self.__del__()  
        