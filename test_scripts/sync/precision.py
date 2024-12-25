# Pico-Irig for Raspberry-Pi Pico
# (c) 2024-12-23 Simon Wood <simon@mungewell.org>
#
# https://github.com/mungewell/pico-irig
#
# Example script for a 'precision trigger', starting a 12KHz clocked
# StateMachine from a trigger pin with ~16ns accuracy.
#
# This example just 'toggles a pin', but can be adjusted for more
# complicated purposes.
#
# MIT license - go make something cool....
    
import rp2
import utime
from machine import Pin, disable_irq, enable_irq, mem32, freq, I2C

from micropython import schedule, alloc_emergency_exception_buf
alloc_emergency_exception_buf(100)

# https://github.com/pangopi/micropython-DS3231-AT24C32
from libs.ds3231 import DS3231

# globals used in example 'main()'
trigger_rising = False
trigger_rtc = True

core_dis = [0, 0]
ret = 0

# ---
@rp2.asm_pio(set_init=[rp2.PIO.OUT_LOW])

def precision_12k():
    wrap_target()                   # loop length = 1000 SM-clks @ 12MHz

    irq(4)

    set(x, 29)                      # some thing 'weird' about detecting 1st address
    set(y, 26)                      # probably with the way 'wrap()' works...

    set(pins, 0)                    # note: address = 'base+2'
    irq(block, 4)                   # Wait for Sync'ed start
                                    # --
                                    # triggered...
    set(pins, 1) [6]
    label("before")                 
    jmp(x_dec, "before") [22]       # 30 * 23 = 690, + 7 = 697
                                    # ~= 58 us
                                    # --
    irq(rel(0)) 				    # set IRQ to trigger handler
                                    # IRQ response time ~10-20us
                                    # note: address = 'base+7'
    label("after")                  
    jmp(y_dec, "after") [10]        # 27 * 11 = 297, + (1 * 6) = 303
                                    # ~= 25 us
    wrap()


# slight adjusted to trigger IRQ earlier, may help with trigger reliability
@rp2.asm_pio(set_init=[rp2.PIO.OUT_LOW])

def precision_12ka():
    wrap_target()                   # loop length = 1000 SM-clks @ 12MHz

    irq(4)

    set(x, 26)                      # some thing 'weird' about detecting 1st address
    set(y, 29)                      # probably with the way 'wrap()' works...

    set(pins, 0)                    # note: address = 'base+2'
    irq(block, 4)                   # Wait for Sync'ed start
                                    # --
                                    # triggered...
    set(pins, 1) [9]
    label("before")                 
    jmp(x_dec, "before") [21]       # 27 * 22 = 594, + 10 = 604
                                    # ~= 50 us
                                    # --
    irq(rel(0)) 				    # set IRQ to trigger handler
                                    # IRQ response time ~10-20us
                                    # note: address = 'base+7'
    label("after")                  
    jmp(y_dec, "after") [12]        # 30 * 13 = 390, + (1 * 6) = 396
                                    # ~= 33 us
    wrap()


# trigger IRQ even earlier
@rp2.asm_pio(set_init=[rp2.PIO.OUT_LOW])

def precision_12kb():
    wrap_target()                   # loop length = 1000 SM-clks @ 12MHz

    irq(4)

    set(x, 30)                      # Note: some thing 'weird' about detecting/using
    set(y, 30)                      # 1st address probably with the way 'wrap()' works...

    set(pins, 0)                    # note: address = 'base+2'
    irq(block, 4)                   # Wait for Sync'ed start
                                    # --
                                    # triggered...
    set(pins, 1) [1]
    label("before")                 
    jmp(x_dec, "before") [12]       # 31 * 13 = 403, + 2 = 405
                                    # ~= 33 us
                                    # --
    irq(rel(0)) 				    # set IRQ to trigger handler
                                    # IRQ response time ~10-20us
                                    # note: address = 'base+7'
    label("after")                  
    jmp(y_dec, "after") [18]        # 31 * 19 = 589, + (1 * 6) = 595
                                    # ~= 49 us
    wrap()


@rp2.asm_pio(set_init=[rp2.PIO.OUT_LOW], sideset_init=[rp2.PIO.OUT_LOW])

def start_from_pin_rising():
    wrap_target()

    wait(0, pin, 0) .side(0)
    wait(1, pin, 0)

    irq(clear, 4) .side(1)          # Trigger SM-0
    irq(rel(0)) [2]

    # will stick at this 'address' depending
    # on when exactly the Sync occurs

    label("minus_13")
    jmp(pin, "minus_13") .side(0)
    label("minus_12")
    jmp(pin, "minus_12") .side(1)
    label("minus_11")
    jmp(pin, "minus_11") .side(0)
    label("minus_10")
    jmp(pin, "minus_10") .side(1)
    label("minus_9")
    jmp(pin, "minus_9") .side(0)        # <--- nominal
    label("minus_8")
    jmp(pin, "minus_8") .side(1)
    label("minus_7")
    jmp(pin, "minus_7") .side(0)
    label("minus_6")
    jmp(pin, "minus_6") .side(1)
    label("minus_5")
    jmp(pin, "minus_5") .side(0)
    label("minus_4")
    jmp(pin, "minus_4") .side(1)
    label("minus_3")
    jmp(pin, "minus_3") .side(0)
    label("minus_2")
    jmp(pin, "minus_2") .side(1)
    label("minus_1")
    jmp(pin, "minus_1") .side(0)
    label("zero")                 
    jmp(pin, "zero")    .side(1)        # address = 'top'

    wrap()


@rp2.asm_pio(set_init=[rp2.PIO.OUT_LOW], sideset_init=[rp2.PIO.OUT_LOW])

# sideset pin is only for debug, it is not needed for operation

def start_from_pin_falling():
    wrap_target()

    wait(1, pin, 0) .side(0)
    wait(0, pin, 0)

    irq(clear, 4) .side(1)          # Trigger SM-0
    irq(rel(0)) [2]

    # will stick at this 'address' depending
    # on when exactly the Sync occurs

    label("minus_13")
    jmp(pin, "minus_13") .side(0)
    label("minus_12")                   # earliest seen
    jmp(pin, "minus_12") .side(1)
    label("minus_11")
    jmp(pin, "minus_11") .side(0)
    label("minus_10")
    jmp(pin, "minus_10") .side(1)
    label("minus_9")
    jmp(pin, "minus_9") .side(0)
    label("minus_8")
    jmp(pin, "minus_8") .side(1)
    label("minus_7")
    jmp(pin, "minus_7") .side(0)
    label("minus_6")
    jmp(pin, "minus_6") .side(1)
    label("minus_5")
    jmp(pin, "minus_5") .side(0)
    label("minus_4")
    jmp(pin, "minus_4") .side(1)
    label("minus_3")                    # latest seen
    jmp(pin, "minus_3") .side(0)
    label("minus_2")
    jmp(pin, "minus_2") .side(1)
    label("minus_1")
    jmp(pin, "minus_1") .side(0)
    label("zero")                 
    jmp(pin, "zero")    .side(1)        # address = 'top'

    wrap()


@rp2.asm_pio(set_init=[rp2.PIO.OUT_LOW], out_init=[rp2.PIO.OUT_LOW])

def toggle_pin():
    wrap_target()
    mov(pins, invert(pins))
    wrap()

# ---

@micropython.asm_thumb

def precision_handler(r0):
    align   (4)                 # DO NOT MODIFY
    mov     (r7, pc)            # PC points to the table, so does r7 now
    b       (func_entry)        # DO NOT MODIFY

    # --
    # embedded table with constants
    align   (4)
    data    (4, 0x502000cc)     #  0x00 - Bank 1 - SM0_EXECCTRL, +8 for SM0_ADDR (ie 'counter')
    data    (4, 0x502000e4)     #  0x04 - Bank 1 - SM1_EXECCTRL, +8 for SM1_ADDR (ie 'phase')

    # trigger 1
    data    (4, 0x50300000)     #  0x08 - Bank 2 - CTRL Register
    data    (4, 0x00000101)     #  0x0C - Align Dividers for SM4 and Enable SM4

    # trigger 2 - optional
    data    (4, 0x50400000)     #  0x10 - Bank 3 - CTRL Register - ie RP2350 only
    data    (4, 0x00000F0F)     #  0x14 - Align Dividers for all and Enable SM11/10/9/8

    align   (2)
    # --
    label   (check_a)
    cmp     (r2, r5)
    beq     (check_b)           # ie taken for Flow-5

    nop     ()
    nop     ()
    b       (check_c)

    # --
    label   (check_b)
    nop     ()
    nop     ()
    b       (aligned)

    # --
    label   (func_entry)

    # checking SM-1 Address (ie Phase)
    ldr     (r1, [r7, 0x04])    # loads 0x502000e4 into r1
    ldr     (r3, [r1, 0])       # value from 0x502000e4=SM1_EXECCTRL into r3
    mov     (r0, 12)
    lsr     (r3, r0)
    mov     (r0, 0x1f)
    and_    (r3, r0)            # computed SM-1 address 'top'
    '''
    mov     (r3, 0x17)          # DEBUG: this is SM-1 address 'top'
    '''

    sub     (r3, r3, 7)
    sub     (r3, r3, 7)
    ldr     (r0, [r1, 8])       # value from 0x502000ec=SM1_ADDR into r0
    sub     (r0, r0, r3)

    cmp     (r0, 12)            # safety check, should be < 12
    blt     (phase_ok)
    b       (abort)

    label(phase_ok)
    mov     (r3, 1)
    lsl     (r0, r3)            # double value needed for 'data()'

    # --
    # checking SM-0 Address (ie Counter)
    ldr     (r1, [r7, 0x00])    # loads 0x502000cc into r1
    ldr     (r5, [r1, 0])       # value from 0x502000cc=SM1_EXECCTRL into r5
    mov     (r3, 7)
    lsr     (r5, r3)
    mov     (r3, 0x1f)
    and_    (r5, r3)            # computed SM-0 address 'base'
    add     (r5, r5, 1)
    '''
    mov     (r5, 0x18)          # DEBUG: this is SM-0 address 'base+1'
    '''

    # did we enter IRQ handler too late?
    add     (r6, r5, 6)
    '''
    mov     (r6, 0x1e)          # DEBUG: this is SM-0 address 'base+7'
    '''

    ldr     (r2, [r1, 8])       # value from 0x502000d4=SM0_ADDR into r3
    cmp     (r2, r6)            # NOTE: this is SM-0 address 'base+7'
    blt     (abort)             # SM-0 has already looped, you are too slow!

    # ---
    # NEED to be cycle accurate from here....
    label   (wait_for_it)
    ldr     (r2, [r1, 8])       # value from 0x502000d4=SM0_ADDR into r2
    cmp     (r2, r5)
    bne     (wait_for_it)

    add     (r5, r5, 1)

    ldr     (r3, [r1, 8])       # value from 0x502000d4=SM0_ADDR into r3
    ldr     (r4, [r1, 8])       # value from 0x502000d4=SM0_ADDR into r4

    cmp     (r3, r4)
    beq     (check_a)           # taken for Flow-1,2,5

    nop     ()
    nop     ()
    nop     ()
    nop     ()

    label   (check_c)
    ldr     (r2, [r1, 8])       # value from 0x502000d4=SM0_ADDR into r2
    cmp     (r2, r5)
    beq     (aligned)           # ie taken for Flow-1,3
    
    # --
    label   (aligned)

    # pre-load trigger 1 values
    ldr     (r3, [r7, 0x08])    # loads 0x50300000 into r3
    ldr     (r4, [r7, 0x0C])    # loads 0x00000101 into r4
    # pre-load trigger 2 values
    ldr     (r5, [r7, 0x10])    # loads 0x50400000 into r5
    ldr     (r6, [r7, 0x14])    # loads 0x00000F0F into r6

    #nop     ()                  # spare/delay
    #nop     ()                  # spare/delay

    # --
    # write correcting SM-0 vs SM-1 'phase' with r0 value
    # every increament of 2 adds 8.3ns

    label   (write)

    data    (2, 0x4487)         # add(r15, r15, r0)
    nop     ()
    nop     ()
    nop     ()
    nop     ()
    nop     ()
    nop     ()
    nop     ()
    nop     ()
    nop     ()
    nop     ()
    nop     ()
    str     (r4, [r3, 0])       # Trig-1: Reset SM4's DivClock and start it
    #str     (r6, [r5, 0])       # Trig-2: Reset SM11/10/9/8 and start them

    # --
    label   (abort)

    #mov     (r0, 0)


def mp_irq_handler(m):
    global core_dis, ret
    
    #core_dis[mem32[0xd0000000]] = disable_irq()

    '''
    # reset the clock-phases with CLKDIV_RESTART
    mem32[0x50200000] = 0x00000407
    '''
    ret = precision_handler(0)
    
    #enable_irq(core_dis[mem32[0xd0000000]])

#---------------------------------------------

if __name__ == "__main__":
    # configure the PPS pin as pull-up
    pps = Pin(18, Pin.IN, Pin.PULL_UP)
    utime.sleep(2)
    
    # Start the StateMachines using a 1PPS signal
    # (for now using a RTC chip as our 1PPS reference)
    if trigger_rtc:
        ds = DS3231(I2C(0, sda=Pin(16), scl=Pin(17)))
        ds.square_wave(freq=ds.FREQ_1)
        print("RTC SquareWave started")
        utime.sleep(0.1)

    # Ensure the CPU frequency is optimal
    # ie. does not cause fractional div on StateMachine clocks
    cpu_freq = 120_000_000

    if freq() != cpu_freq:
        freq(cpu_freq)

    irig_sm = []
    irig_sm.append(rp2.StateMachine(0, precision_12k, freq=int(cpu_freq / 10), \
                            set_base=Pin(4)))

    if trigger_rising:
        irig_sm.append(rp2.StateMachine(1, start_from_pin_rising, freq=cpu_freq, \
                            set_base=Pin(7), sideset_base=Pin(7),\
                            in_base=Pin(18), jmp_pin=Pin(4)))
    else:
        irig_sm.append(rp2.StateMachine(1, start_from_pin_falling, freq=cpu_freq, \
                            set_base=Pin(7), sideset_base=Pin(7),\
                            in_base=Pin(18), jmp_pin=Pin(4)))

    irig_sm.append(rp2.StateMachine(4, toggle_pin, freq=12_000, \
                            set_base=Pin(6), in_base=Pin(6), out_base=Pin(6)))

    '''
    print("SM-0")
    print("Top 0x%8.8x" % ((mem32[0x502000cc] >> 12) & 0x1f))
    print("Bot 0x%8.8x" % ((mem32[0x502000cc] >> 7) & 0x1f))
    print()

    print("SM-1")
    print("Top 0x%8.8x" % ((mem32[0x502000e4] >> 12) & 0x1f))
    print("Bot 0x%8.8x" % ((mem32[0x502000e4] >> 7) & 0x1f))
    print()
    '''

    # enable the IRQ handler
    irig_sm[0].irq(handler=precision_handler, hard=True)
    #irig_sm[0].irq(handler=mp_irq_handler, hard=True)
    utime.sleep(0.1)

    # reset Dividers for SM-1 and SM-0
    mem32[0x50200000] = 0x00000300

    # loop, waiting for a successful trigger
    while True:
        if trigger_rtc:
            while pps.value() == trigger_rising:
                # wait for PPS to deassert first, as some are 1Hz signals...
                utime.sleep(0.1)

        # Start SM-0 & SM-1
        mem32[0x50200000] = 0x00000003

        if trigger_rtc:
            while pps.value() != trigger_rising:
                # wait for PPS to assert
                utime.sleep(0.1)

        utime.sleep(0.1)
        #print("0x%8.8x" % mem32[0x50200000])

        if (mem32[0x50300000] & (1 << 0)):
            print("SM-4 has started")#, ret =", ret)

            # Stop SM-0 & SM-1
            mem32[0x50200000] = 0x00000000
            break

        print("try, try again...")#0x%8.8x"% ret)

        # stop SM-4 and loop to trigger again
        mem32[0x50300000] = 0x00000000
        ret = 0

    
    while True:
        # loop forever
        utime.sleep(0.5)

