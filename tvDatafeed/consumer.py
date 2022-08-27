import threading, queue

class Consumer(threading.Thread):
    
    def __init__(self, seis, callback):
        super().__init__()

        self._buffer=queue.Queue()               
        self.seis=seis
        self.callback=callback
    
    def __repr__(self):
        return f'Consumer({repr(self.seis)},{self.callback.__name__})'
    
    def __str__(self):
        return f'{repr(self.seis)},callback={self.callback.__name__}'
    
    def run(self):
        '''
        Callback thread
        '''
        while True:
            data=self._buffer.get()
            if data is None:
                break
            
            self.callback(self.seis, data)
        
        self.seis=None # delete references
        self.callback=None
        self._buffer=None
    
    def put(self, data):
        '''
        Put new data into buffer to be processed
        '''
        self._buffer.put(data)
    
    def del_consumer(self):
        '''
        Shutdown the callback thread and remove from Seis
        '''
        self.seis.del_consumer(self)
    
    def stop(self):
        '''
        Shutdown the callback thread and remove from Seis
        '''
        self._buffer.put(None)
        