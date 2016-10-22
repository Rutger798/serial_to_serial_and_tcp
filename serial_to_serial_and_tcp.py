#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
    author: Rutger
    This script will connect a serial port to a virtual serial port and a TCP connection.
    
    Usage: python {serial in} {serial out} {tcp port}
    Example :python /dev/mySensorsCOM /dev/ttyMySensors 5003
"""

import os
import sys
import pty
import serial
import time
import socket
import asyncore
from multiprocessing import Process, Queue

SERIAL_PORT_BAUT = 115200   #This is the serial baud rate
TCP_RECV_BUFFER_SIZE = 1024 

"""
The TCP server is a asynchronous TCP server which will read/write from the TX and RX queue's
"""
class TcpServer(asyncore.dispatcher):
    def __init__(self, address, port, RxQueue, TxQueue,):
        self.RxQueue                = RxQueue
        self.TxQueue                = TxQueue
        self.buffer                 = ""
        asyncore.dispatcher.__init__(self)
        self.create_socket(socket.AF_INET, socket.SOCK_STREAM)
        self.bind((address, int(port)))
        self.listen(1)
    def run_forever(self):
        asyncore.loop()
    def handle_accept(self):
        socket, address = self.accept()
        print 'Connection by', address
        asyncore.dispatcher.__init__(self, conn_sock)
        print "created handler; waiting for loop"
    def handle_read(self):
        data = self.recv(TCP_RECV_BUFFER_SIZE)
        print "TcpRx:\t" + data
        if (len(data) > 0):
            self.RxQueue.put(data)
        else:
            print "got null data"
    def handle_write(self):
        if len(self.buffer) > 0:
            sent = self.send(self.buffer)
            print "send next chunk data"
            self.buffer = self.buffer[sent:]
        else:
            if not self.TxQueue.empty():        
                self.buffer = self.TxQueue.get() ##This is a blocking call while no data is avalible 
                print "TcpTx:\t" + self.buffer
                sent = self.send(self.buffer)
                self.buffer = self.buffer[sent:]
            else :
                time.sleep(0.01)
    def handle_error(self):
        print "socket encountered an error"
    def handle_expt(self):
        print "socket received OOB data (not really used in practice)"
    def handle_close(self):
        print "close socket"
        self.close()

def SerialToQueue(serialObj, queue):
    # ReadOut the serial port and write it to the outputs
    while True:    
        line = serialObj.readline()
        print "Rx:\t" + line
        if len(line) > 0:
            queue.put(line)
    
def QueueToSerial(serialObj, queue):
    while True:
        line = queue.get() ##This is a blocking call while no data is avalible 
        print "Tx:\t" + line
        serialObj.write(line)
        
def BindGwRxToClonesTx(queueIn, queueOut1, queueOut2):
    while True:
        data = queueIn.get()    #If we get data from the MySensors Gw we want to transmitt it to the TCP and clone serial
        queueOut1.put(data)
        queueOut2.put(data)

def BindGwTxToClonesRx(queueOut, queueIn1, queueIn2):
    while True:
        #while loop until one of the two queue's is not empty any more then continue
        while not queueIn1.empty():
            data = queueIn1.get()
            queueOut.put(data)
        while not queueIn2.empty():
            data = queueIn2.get()
            queueOut.put(data)
        time.sleep(0.01)
    
#-----------------------------------------------------------------
#   The init functions for creating a Serial, VertialeSerial and TCP Socket
#-----------------------------------------------------------------    
def InputSerialInit(portName):
    print "Main Serial port name is:" + portName
    return serial.Serial(portName, SERIAL_PORT_BAUT, bytesize=8, parity=serial.PARITY_NONE, stopbits=1, timeout=None)
    
def OutputSerialInit(portName):
    USER = "pi"
    SERIAL_MASTER = "/dev/ttyPyMaster"
    command = "socat -d -d  pty,link=" + SERIAL_MASTER + ",raw,echo=0,user=" + USER + " pty,link=" + portName + ",raw,echo=0,user=" + USER
    print "Clone COM master name is: " + SERIAL_MASTER
    print "Clone COM slave name is: " + portName
    command = command + "&" #run process in background
    os.system(command)
    time.sleep(1)
    #The slave port is used for a other application the master side we use to read an write data to
    #So after this point we will not do anything with the slave side
    return serial.Serial(SERIAL_MASTER, SERIAL_PORT_BAUT, bytesize=8, parity=serial.PARITY_NONE, stopbits=1, timeout=None)

if __name__ == "__main__":
    inputPort = sys.argv[1] #input serial port (mySensors GW)
    outputPort = sys.argv[2] #output serial port (for a connection to openhab)
    tcpPort = sys.argv[3] #output TCP port (for the Controller for MySensors)

    mySensorGWSerialObj = InputSerialInit(inputPort)    #open the com
    CloneSerialObj = OutputSerialInit(outputPort)       #open the com
    
    #-----------------------------------------------------------------
    #   Read and write the MySensor Gateway to queue's
    #-----------------------------------------------------------------
    print "Create a taks to read and write to the MySensors serial port"
    mySensorGWRxQueue = Queue()
    thread1 = Process(target=SerialToQueue, args=(mySensorGWSerialObj, mySensorGWRxQueue))
    thread1.start()

    mySensorGWTxQueue = Queue()
    thread2 = Process(target=QueueToSerial, args=(mySensorGWSerialObj, mySensorGWTxQueue))
    thread2.start()
    
    #-----------------------------------------------------------------
    #   Read and write the virtual/clone serial port to queue's
    #-----------------------------------------------------------------
    print "Create a taks to read and write Clone serial port"
    cloneSerialRxQueue = Queue()
    thread3 = Process(target=SerialToQueue, args=(CloneSerialObj, cloneSerialRxQueue))
    thread3.start()

    cloneSerialTxQueue = Queue()
    thread4 = Process(target=QueueToSerial, args=(CloneSerialObj, cloneSerialTxQueue))
    thread4.start()

    #-----------------------------------------------------------------
    #   Read and write the TCP server data to queue's
    #-----------------------------------------------------------------
    print "Create a taks to read and write to the TCP socket"
    CloneTCPObjRxQueue = Queue()    
    CloneTCPObjTxQueue = Queue()

    TcpServerObj = TcpServer("", tcpPort, CloneTCPObjRxQueue, CloneTCPObjTxQueue)
    thread5 = Process(target=TcpServerObj.run_forever, args=()) #function is bocking
    thread5.start()

    #-----------------------------------------------------------------
    #   Connect the mySensor RX queue to the the TX queues of the clones
    #-----------------------------------------------------------------
    print "Bind mysensor RX to clone serial TX and tcp TX"
    thread6 = Process(target=BindGwRxToClonesTx, args=(mySensorGWRxQueue, cloneSerialTxQueue, CloneTCPObjTxQueue))
    thread6.start()
    
    #-----------------------------------------------------------------
    #   Connect the mySensor TX queue to the the RX queues of the clones
    #-----------------------------------------------------------------
    print "Bind mysensor TX to clone serial RX and tcp RX"
    thread7 = Process(target=BindGwTxToClonesRx, args=(mySensorGWTxQueue, cloneSerialRxQueue, CloneTCPObjRxQueue))
    thread7.start()
    
    raw_input("Any key will quit the script")
    print "QUITING THE SCRIPT"
    
    thread1.terminate()
    thread2.terminate()
    thread3.terminate()
    thread4.terminate()
    thread5.terminate()
    thread6.terminate()
    thread7.terminate()

    mySensorGWSerialObj.close() #Close the Serial port
    CloneSerialObj.close() #Close the Serial port
    TcpServerObj.close()
    sys.exit(0)
