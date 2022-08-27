import tvDatafeed

class Seis(object): # TODO: add a __repr__ method so user can easily see what Seis contains
    """
    Contain Seis related data
    
    Holds a set of symbol, exchange and interval values in addition to
    keeping a set of consumer thread input buffers (CTIB) each of which 
    provides an input to a consumer (callback) thread that is waiting 
    for new bar data for this symbol-exchange-interval set (Seis). The
    CTIB is actually a Queue object acting as a FIFO to consumer threads
    for receiving new bar data. There is an attribute 'updated' which 
    holds datetime value. This is meant to hold the date and time of when
    was the latest bar released for this Seis.
    
    Methods
    -------
    add_ctib(buffer)
        Add consumer thread input buffer
    del_ctib(ctib_id)
        Remove consumer thread input buffer
    get_ctib(ctib_id)
        Get consumer thread input buffer
    get_ctibs()
        Retrieve all consumer thread input buffers for this Seis
    """

    def __init__(self, symbol, exchange, interval):
        """
        Parameters
        ----------
        symbol : str
            asset or ticker name on the exchange
        exchange : str
            exchange name on TradingView listing the symbol
        interval : tvDatafeed.Interval
            symbol updating interval option in TradingView
        """
        self._symbol=symbol
        self._exchange=exchange
        self._interval=interval
        
        self._tvdatafeed=None 
        self._consumers=[]
        self.updated=None # datetime of the data bar that was last retrieved from TradingView
    
    def __eq__(self, other):
        # Compare two seis instances to decide if they are equal
        #
        # Instances are equal if symbol, exchange and interval attributes
        # are of same value.
        #
        # Parameters
        # ----------
        # other : seis.Seis
        #    the other instance to compare against
        #
        # Returns
        # -------
        # boolean 
        #     True if equal, False otherwise
        if isinstance(other, self.__class__): # make sure that they are the same class 
            if self.symbol == other.symbol and self.exchange == other.exchange and self.interval == other.interval: # these attributes need to be identical
                return True
        # TODO : add an option to compare Seis with list and tuple containing 3 string elements (symb, exch, inter)
        
        return False
    
    def __repr__(self):
        return f'Seis("{self._symbol}","{self._exchange}",{self._interval})'
    
    def __str__(self):
        return "symbol='"+self._symbol+"',exchange='"+self._exchange+"',interval='"+self._interval.name+"'"

    @property # read-only attribute
    def symbol(self):
        return self._symbol
    
    @property # read-only attribute
    def exchange(self):
        return self._exchange
    
    @property # read-only attribute
    def interval(self):
        return self._interval
    
    @property
    def tvdatafeed(self):
        return self._tvdatafeed
    
    @tvdatafeed.setter
    def tvdatafeed(self, value):
        if (self._tvdatafeed) is not None:
            raise AttributeError("Cannot overwrite attribute, need to delete it first")
        elif not isinstance(value, tvDatafeed.TvDatafeedLive):
            raise ValueError("Argument must be instance of TvDatafeed") 
        else:
            self._tvdatafeed=value
    
    @tvdatafeed.deleter
    def tvdatafeed(self):
        self._tvdatafeed=None
    
    def add_seis(self):
        '''
        Add this Seis into MAR list of specified TvDatafeed
        '''
        self._tvdatafeed.add_seis(self)
    
    def new_consumer(self, callback):
        '''
        Create a new consumer and add to TvDatafeed
        '''
        if self._tvdatafeed is None:
            raise NameError("TvDatafeed not provided")
        
        return self._tvdatafeed.new_consumer(self, callback) # methods go through tvdatafeed to acquire lock and make it thread safe
    
    def del_consumer(self, consumer):
        '''
        Remove the consumer from TvDatafeed
        '''
        if self._tvdatafeed is None:
            raise NameError("TvDatafeed not provided")
        
        self._tvdatafeed.del_consumer(consumer) 
    
    def add_consumer(self, consumer):
        '''
        Add consumer to this Seis consumers list, method used only by tvdatafeed
        '''
        self._consumers.append(consumer)
        
    def pop_consumer(self, consumer):
        '''
        Remove the consumer from this Seis consumer list, method used only by tvdatafeed
        '''
        if consumer not in self._consumers:
            raise NameError("Consumer does not exist in the list")
        self._consumers.remove(consumer)
        
    def get_hist(self, n_bars):
        '''
        One-time retrieval of bar data for this Seis
        '''
        raise NotImplementedError 
    
        if self._tvdatafeed is None:
            raise NameError("TvDatafeed not provided")
        
        return self._tvdatafeed.get_hist(self, n_bars) # TODO: make get_hist method such that it can accept old argument set (from original TvDatafeed) and Seis
    
    def del_seis(self):
        '''
        Remove the Seis from TvDatafeed
        '''
        if self._tvdatafeed is None:
            raise NameError("TvDatafeed not provided")
        
        self._tvdatafeed.del_seis(self)
    
    def get_consumers(self):
        '''
        Retrieve a list of consumers added to this Seis 
        '''
        return self._consumers
    
    def __del__(self):
        raise NotImplementedError()
    