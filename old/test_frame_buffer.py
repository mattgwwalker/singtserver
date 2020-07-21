import pytest
import numpy
from frame_buffer import *


def test_init():
    fb = FrameBuffer(2,1)
    assert fb is not None

def test_put():
    fb = FrameBuffer(100,1)
    fb.put([1])
    fb.put([2])

def test_put_2d():
    fb = FrameBuffer(100,2)
    fb.put([1,2])
    
    
def test_get():
    fb = FrameBuffer(2,1)
    value = [1]
    fb.put(value)
    x = fb.get(1)
    assert x == value

def test_get_2d():
    fb = FrameBuffer(2,2)
    value = [[1,2]]
    fb.put(value)
    x = fb.get(1)
    assert (x == value).all()
    

def test_get_leaves_next_data():
    fb = FrameBuffer(2,2)
    value1 = [[1,2]]
    value2 = [[3,4]]
    fb.put(value1)
    fb.put(value2)
    x = fb.get(1)
    assert (x == value1).all()
    x = fb.get(1)
    assert (x == value2).all()
    x = fb.get(1)
    assert (x == [[0,0]]).all()
