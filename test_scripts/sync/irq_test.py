import rp2
import utime
from machine import Pin, disable_irq, enable_irq, mem32, freq, I2C

from micropython import schedule, alloc_emergency_exception_buf
alloc_emergency_exception_buf(100)

# https://github.com/pangopi/micropython-DS3231-AT24C32
from libs.ds3231 import DS3231


@rp2.asm_pio()

def start_from_pin_rising_irq():
    wrap_target()
    wait(0, pin, 0)
    wait(1, pin, 0)

    irq(rel(0))					    # set IRQ for ticks_us monitoring
    wrap()


@rp2.asm_pio()

def start_from_pin_falling_irq():
    wrap_target()
    wait(1, pin, 0)
    wait(0, pin, 0)

    irq(rel(0))					    # set IRQ for ticks_us monitoring
    wrap()

# ---

@micropython.asm_thumb

def irq_handler(r0):
    align   (4)             # DO NOT MODIFY
    mov     (r7, pc)        #   PC points to the table, so does r7 now
    b       (func_entry)    # DO NOT MODIFY

    # embedded table with constants
    align   (4)
    data    (2, 0x0040)     #  0 - Set GPIO 6
    data    (2, 0x0000)     #  2
    data    (2, 0x0014)     #  4 - GPIO_OUT_SET 
    data    (2, 0xd000)     #  6

    align   (2)
    label   (func_entry)
    ldr     (r0, [r7, 4])       # gets 0xD0000014 into r0
    ldr     (r2, [r7, 0])       # gets 0x00000040 into r2

    str     (r2, [r0, 0])

    # when fuction returns, r0 is the return value

#---------------------------------------------

if __name__ == "__main__":
    # Ensure the CPU frequency is optimal
    # ie. does not cause fraction div on StateMachine clocks
    cpu_freq = 120_000_000
    if freq() != cpu_freq:
        freq(cpu_freq)

    # configure the PPS pin
    out = machine.Pin(6, machine.Pin.OUT, value=0)
    pps = machine.Pin(18, machine.Pin.IN, machine.Pin.PULL_UP)
    
    # Start the StateMachines using a 1PPS signal
    # (for now using a RTC chip as our 1PPS reference)
    ds = DS3231(I2C(0, sda=Pin(16), scl=Pin(17)))
    ds.square_wave(freq=ds.FREQ_1)
    print("RTC SquareWave started")
    utime.sleep(0.1)

    irig_sm = []
    if False:
        irig_sm.append(rp2.StateMachine(0, start_from_pin_rising_irq, freq=cpu_freq, \
                            in_base=Pin(18), jmp_pin=Pin(18)))
    else:
        irig_sm.append(rp2.StateMachine(0, start_from_pin_falling_irq, freq=cpu_freq, \
                            in_base=Pin(18), jmp_pin=Pin(18)))

    # Stage-1 trigger, via IRQ handler
    irig_sm[0].irq(handler=irq_handler, hard=True)

    while pps.value() == 1:
        # wait for PPS to deassert first, as some are 1Hz signals...
        utime.sleep(0.1)
    print("Low level")
        
    # start just one SM
    mem32[0x50200000] = 0x00000001
    
    while True:
        utime.sleep(0.5)
        out = machine.Pin(6, machine.Pin.OUT, value=0)
        print("Pin cleared")
        utime.sleep(0.5)

    
    
