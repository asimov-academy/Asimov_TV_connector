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

from datetime import datetime as dt
from dateutil.relativedelta import relativedelta as rd
import threading

class Seis(object):
    """
    Contains a set of symbol, exchange and interval values
    
    Holds a set of symbol, exchange and interval values in addition to
    keeping a set of callback queues each of which provides a pipe to
    a callback thread that is waiting for new data on the other side of 
    the queue. There is also an attribute 'updated' which holds a datetime
    value. This is meant to hold the date and time of when was the latest
    bar released for this symbol-exchange-interval set (seis).
    
    Methods
    -------
    add_queue(queue)
        Add queue for this seis
    del_queue(queue_id)
        Remove a queue 
    get_queue(queue_id)
        Get a queue object
    get_queues()
        Retrieve all queue objects for this seis
    """

    def __init__(self, symbol, exchange, interval):
        """
        Parameters
        ----------
        symbol : str
            asset or ticker name on the exchange
        exchange : str
            exchange name on TradingView.com listing the symbol
        interval : tvDatafeed.Interval
            symbol updating interval option 
        """
        self.symbol=symbol
        self.exchange=exchange
        self.interval=interval
        
        self.updated=None # tracks last update datetime for this seis data sample
        self._callback_queues={} # dictionary containing queues for all the callback function threads for this seis
    
    def __eq__(self, other):
        # Compare two seis instances to decide if they are equal
        #
        # Instances are equal if symbol, exchange and interval attributes
        # are of same value.
        #
        # Parameters
        # ----------
        # other : seis.seis
        #    the other instance to compare against
        #
        # Returns
        # -------
        # boolean 
        #     True if equal, False otherwise
        if isinstance(other, self.__class__): # make sure that they are the same class 
            if self.symbol == other.symbol and self.exchange == other.exchange and self.interval == other.interval: # these attributes need to be identical
                return True

        return False
    
    def add_queue(self, queue):
        """
        Add queue for this seis
        
        Parameters
        ----------
        queue : queue.Queue
            queue instance used to send data to a callback thread
            
        Returns
        -------
        queue_id : int
            unique id number to reference this queue instance
        """
        for i in range(len(self._callback_queues)+1): # keys are integer values starting from 0, loop through all keys + 1
            if i not in self._callback_queues: # if any key before the highest key has been released (deleted) then we shall use that one, otherwise we take new highest number
                self._callback_queues[i]=queue
                return i
     
    def del_queue(self, queue_id):
        """
        Remove a queue 
        
        Parameters
        ----------
        queue_id : int
            id number to reference particular queue instance
            
        Returns
        -------
        queue.Queue
            instance of queue that is referenced with this queue_id
        """
        return self._callback_queues.pop(queue_id, None) # remove key-value pair from dict, if not existing then None is returned otherwise the queue object itself is returned
    
    def get_queue(self,queue_id):
        """
        Get a queue object
        
        Parameters
        ----------
        queue_id : int
            id number to reference particular queue instance
            
        Returns
        -------
        queue.Queue
            instance of queue that is referenced with this queue_id
        """
        return self._callback_queues[queue_id]
        
    def get_queues(self):
        """
        Retrieve all queue objects for this seis 
        
        Returns
        -------
        list
            list of queue instances for this seis
        """
        return self._callback_queues.values()

class SeisManager(object):
    """
    Collect and manage all seis objects
    
    Group all seis and provide methods to add new seis or remove already
    existing seis, managing update times for all seis and find the soonest
    update time, provide access to individual seis and its callback queues
    and also make seis management thread safe by implementing locks. Keeps
    a list of datetimes when each interval will update next and provides a
    method to retrieve datetime for interval(s) which will update next - 
    the user can wait for these events
    
    Methods
    -------
    add_seis(symbol, exchange, interval)
        Add new seis to be monitored for updates
    get_seis(seis_id)
        Return instance of the seis referenced by seis_id
    del_seis(seis_id)
        Remove seis from monitoring list
    get_interval(interval)
        Return datetime of next update (in TradingView.com) time for this 
        interval
    add_interval(interval, update_dt)
        Add new interval 
    get_seis_list()
        Return all seis in a list
    get_grouped_seis(interval)
        Get all seis grouped by interval
    get_expired_intervals()
        Get a list of intervals which update datetime has passed
    get_trigger_dt()
        Get datetime when next interval(s) will expire
    get_lock(timeout=-1)
        Get threading lock
    drop_lock()
        Free threading lock
    add_queue(seis_id, queue) # TODO: change the queue name into input_fifo - this is more descriptive
        Add new callback thread queue for this seis
    get_queue(seis_id, queue_id)
        Get queue object based on queue_id
    del_queue(seis_id, queue_id)
        Remove the queue from this seis internal queue list
    is_locked()
        Check if lock is in use or not
    is_empty()
        Check if no seis listed to be monitored
    """
    def __init__(self, unique_seis_id):
        """
        Parameters
        ----------
        unique_seis_id : boolean, optional
            Generated symbol-echange-interval set ID integers are unique or not (default True)
        """
        self.unique_seis_id=unique_seis_id 
        self.__seises={} # dictionary which has int as keys and seis objects as values
        self.__grouped_seises={} # dictionary which has lists as values and Interval enum as keys
        self.__update_times={} # dictionary which has datetime as value and Interval enum as keys
        
        self.__lock=threading.Lock()
        
        # this array contains different time periods available in TradingView; we use them to increment to next execution time
        self.__timeframes={"1":rd(minutes=1), "3":rd(minutes=3), "5":rd(minutes=5), \
                         "15":rd(minutes=15), "30":rd(minutes=30), "45":rd(minutes=45), \
                         "1H":rd(hours=1), "2H":rd(hours=2), "3H":rd(hours=3), "4H":rd(hours=4), \
                         "1D":rd(days=1), "1W":rd(weeks=1), "1M":rd(months=1)}
    
    def add_seis(self, symbol, exchange, interval):
        """
        Add new seis to be monitored for updates
        
        """
        new_seis=Seis(symbol, exchange, interval)
        if new_seis in self.__seises.values(): # if this seis is already among seises that we monitor 
            return list(self.__seises.keys())[list(self.__seises.values()).index(new_seis)] # then simply return the seis_id of the existing seis
        
        if self.unique_seis_id: # seis IDs cannot be re-used
            seis_id=len(self.__seises)+1 # so we just increment everytime
        else:
            for i in range(len(self.__seises)+1): # keys are integer values starting from 0, loop through all keys + 1
                if i not in self.__seises: # if any key before the highest key has been released (deleted) then we shall use that one, otherwise we take new highest number
                    seis_id=i
        
        self.__seises[seis_id]=new_seis
        
        # create a new interval group in grouped seises if not already existing
        if new_seis.interval.value not in self.__grouped_seises:
            self.__grouped_seises[new_seis.interval.value]=[] 
        
        # update the grouped seis list
        for a in self.__seises.values():
            if a not in self.__grouped_seises[a.interval.value]: # if we don't already have it listed
                self.__grouped_seises[a.interval.value].append(a)
                        
        return seis_id
    
    def get_seis(self, seis_id):
        """
        Return instance of the seis referenced by seis_id
        
        """
        if seis_id in self.__seis: 
            return self.__seises[seis_id]
        else: # if this seis does not exists
            return None
    
    def del_seis(self, seis_id):
        """
        Remove seis from monitoring list
        
        """
        self.__grouped_seises[self.__seises[seis_id].interval.value].remove(self.__seises[seis_id])
        if not self.__grouped_seises[self.__seises[seis_id].interval.value]: # if the list is now empty
            del self.__grouped_seises[self.__seises[seis_id].interval.value] # then remove this interval group
            self.__del_timeframe(self.__seises[seis_id].interval) # remove this interval group in timeframes that we monitor as this was last one
        del self.__seises[seis_id]
    
    def get_timeframe(self, interval):
        """
        Return datetime of next update (in TradingView.com) time for this 
        interval
        
        """
        if interval.value in self.__update_times: # if this timeframe is in the monitor list
            return self.__update_times[interval.value] # return datetime object of the next update time for this timeframe
        
        return None # not in the list so return None
    
    def add_timeframe(self, interval, update_dt):
        """
        Add new interval 
        
        """
        if interval.value not in self.__update_times: # not already in the list
            self.__update_times[interval.value]=update_dt+self.__timeframes[interval.value] # update_dt is in the past so add time (interval) to get next update datetime
            return interval.value
        
        return None # if we already have this timeframe under monitoring 
    
    def __del_timeframe(self, interval):
        del self.__update_times[interval.value]
    
    def get_seis_list(self):
        """
        Return all seis in a list
        
        """
        return self.__seises.values()
    
    def get_grouped_seises(self, group):
        """
        Get all seis grouped by interval
        
        """
        return self.__grouped_seises[group]
        
    # def is_listed(self,asset_id): # TODO: remove this method is tested that we do not need it
    #     if asset_id in self.__assets:
    #         return True
    #     else:
    #         return False  
    
    def get_expired_intervals(self):
        """
        Get a list of intervals which update datetime has passed
        
        """
        timeframes_updated=[] # this list will contain interval enum values for which new data is available
        dt_now=dt.now()
        for inter, dt_next_update in self.__update_times.items(): # go through all the interval/timeframes for which we have seises to monitor
            if dt_now >= dt_next_update: # if present time is greater than the time when next sample should become available; or if dt_next_update is None
                self.__update_times[inter] = dt_next_update + self.__timeframes[inter] # change the time to next update datetime (result will be datetime object)
                timeframes_updated.append(inter)
        
        return timeframes_updated
    
    def get_trigger_dt(self):
        """
        Get datetime when next interval(s) will expire
         
        """
        if not self.__update_times: # if dict is empty meaning we are not monitoring any seises at the moment
            return None 
        
        closest_dt=None # temporary variable used to sort out the closest datetime to present datetime
        for dt_next_update in self.__update_times.values():
            if closest_dt is None: # with first sample there is nothing to compare with 
                closest_dt=dt_next_update
                continue
            elif closest_dt > dt_next_update: # all the following samples will be compared with the previous sample
                closest_dt=dt_next_update
                
        return closest_dt # return the closest datetime; returns a datetime object
    
    def get_lock(self, timeout=-1):
        """
        Get threading lock
        """
        self.__lock.acquire(timeout=timeout)
    
    def drop_lock(self):
        """
        Free threading lock
        """
        self.__lock.release()
    
    def add_queue(self, seis_id, queue):
        """
        Add new callback thread queue for this seis
        
        Parameters
        ----------
        seis_id : int
            symbol-exchange-interval set identifier
        queue : queue.Queue
            queue object reference
            
        Returns
        -------
        queue_id : int
            unique id number to reference this queue instance
        """
        return self.__seises[seis_id].add_queue(queue)
    
    def get_queue(self, seis_id, queue_id):
        """
        Get queue object based on queue_id
        
        Parameters
        ----------
        seis_id : int
            symbol-exchange-interval set identifier
        queue_id : int
            queue identifier 
            
        Returns
        -------
        queue.Queue
            queue object or None if no such seis exists
        """
        if seis_id not in self.__seises: # the seis might have already been removed 
            return None
        else:
            return self.__seises[seis_id].get_queue(queue_id)
        
    def del_queue(self, seis_id, queue_id):
        """
        Remove the queue from this seis internal queue list
        
        Parameters
        ----------
        seis_id : int
            symbol-exchange-interval set identifier
        queue_id : int
            queue identifier 
        """
        return self.__seises[seis_id].del_queue(queue_id)

    def is_locked(self):
        """
        Check if lock is in use or not
        
        Returns
        -------
        boolean
            True if locked and False if not
        """
        return self.__lock.locked()
 
    def is_empty(self):
        '''
        Check if no seis listed to be monitored
        
        boolean
            True if empty and False if not
        '''
        if self.__seises:
            return False
        else:
            return True
            