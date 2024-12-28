# Pico-Irig for Raspberry-Pi Pico
# (c) 2024-12-26 Simon Wood <simon@mungewell.org>
#
# https://github.com/mungewell/pico-irig
#
# MIT license - go make something cool....
#
# Basis is that High/Low cycles will be formed with the hack for
# different output levels from (ab)using the internal Pull-Up/-Downs.
#
# External resistors set the relative amplitude of the high vs low cycle.
#
# High Cycle:
#     set(pindirs, 0b11) .side(0b01) [1]		# Zero = Low, High
#     set(pindirs, 0b11) .side(0b11) [3]		# High = High, High
#     set(pindirs, 0b11) .side(0b01) [1]		# Zero = Low, High
#     set(pindirs, 0b11) .side(0b00) [3]		# Low  = Low, Low
#
# Low Cycle:
#     set(pindirs, 0b11) .side(0b01) [1]		# Zero = Low, High
#     set(pindirs, 0b01) .side(0b01) [3]		# high = In-pull Low, High
#     set(pindirs, 0b11) .side(0b01) [1]		# Zero = Low, High
#     set(pindirs, 0b10) .side(0b00) [3]		# low  = Low, In-Pull High
#
# Each symbol takes 12 PIO clocks (at 12KHz for IRIG-B).
#
# The 'current symbol' is passed via the FIFO with 2bits per symbol, these
# are 'extracted' by a separate/synchronized SM and placed on GPIO pins:
#     0b00 - Data '0'
#     0b01 - Data '1'
#     0b10 - Pr, P1..P9, P0

import rp2
import utime
from random import random
from machine import Pin, disable_irq, enable_irq, mem32, freq, I2C

from micropython import alloc_emergency_exception_buf
alloc_emergency_exception_buf(100)

# https://github.com/pangopi/micropython-DS3231-AT24C32
from libs.ds3231 import DS3231

# Clock speeds
irig_freq = 1000		# 1KHz modulation for IRIG-B
#irig_freq = 10000		# 10KHz modulation for IRIG-A
ext_freq = 10000000     # ie when 1PPS is 1 period of 10MHz
cpu_freq = 120000000

# Trigger source
IRIG_FAKE = 0
IRIG_RTC = 1
IRIG_GPS = 2
irig_trigger = IRIG_FAKE

IRIG_PPS_RISING = 0
IRIG_PPS_FALLING = 1
irig_polarity = IRIG_PPS_RISING

# globals
irig_sm = []
irig_fifo = []
irig_seconds = 0.0
irig_fail = 0

ret = 0

# ---
@rp2.asm_pio(set_init=[rp2.PIO.OUT_LOW])

def precision_12k():
    wrap_target()                   # loop length = '1000-1' SM-clks @ 12MHz

    set(x, 29)                      # some thing 'weird' about detecting 1st address
    set(y, 26)                      # probably with the way '[]' or 'wrap()' works...

    set(pins, 0)                    # note: address = 'base+2'
    wait(1, irq, 4)					# Wait for Sync'ed start
                                    # --
                                    # triggered...
    '''
    set(pins, 1) [5]
    '''
    set(pins, 1) [4]                # make 10 CPU cycles earlier
    label("before")
    jmp(x_dec, "before") [22]       # 30 * 23 = 690, + 6 = 696
                                    # ~= 58 us
                                    # --
    irq(rel(0)) 				    # set IRQ to trigger handler
                                    # IRQ response time ~10-20us
                                    # note: address = 'base+7'
    label("after")
    jmp(y_dec, "after") [10]        # 27 * 11 = 297, + (1 * 6) = 303
                                    # ~= 25 us
    wrap()


@rp2.asm_pio(set_init=[rp2.PIO.OUT_LOW], sideset_init=[rp2.PIO.OUT_LOW])

def start_from_pin_rising():
    irq(clear, 4)
    wrap_target()

    wait(0, pin, 0) .side(0)
    wait(1, pin, 0)

    irq(4) .side(1) [5]                 # Trigger SM-0
    irq(rel(0)) [7]

    # will stick at this 'address' depending
    # on when exactly the Sync occurs

    label("phase_0")
    jmp(pin, "phase_0") .side(0)        # earliest seen = 'top-9'
    label("phase_1")
    jmp(pin, "phase_1") .side(1)
    label("phase_2")
    jmp(pin, "phase_2") .side(0)
    label("phase_3")
    jmp(pin, "phase_3") .side(1)
    label("phase_4")
    jmp(pin, "phase_4") .side(0)
    label("phase_5")
    jmp(pin, "phase_5") .side(1)
    label("phase_6")
    jmp(pin, "phase_6") .side(0)
    label("phase_7")
    jmp(pin, "phase_7") .side(1)
    label("phase_8")
    jmp(pin, "phase_8") .side(0)
    label("phase_9")
    jmp(pin, "phase_9") .side(1)        # latest seen = 'top'

    wrap()


@rp2.asm_pio(set_init=[rp2.PIO.OUT_LOW], sideset_init=[rp2.PIO.OUT_LOW])

# sideset pin is only for debug, it is not needed for operation

def start_from_pin_falling():
    irq(clear, 4)
    wrap_target()

    wait(1, pin, 0) .side(0)
    wait(0, pin, 0)

    irq(4) .side(1) [5]                 # Trigger SM-0
    irq(rel(0)) [7]

    # will stick at this 'address' depending
    # on when exactly the Sync occurs

    label("phase_0")
    jmp(pin, "phase_0") .side(0)        # earliest seen = 'top-9'
    label("phase_1")
    jmp(pin, "phase_1") .side(1)
    label("phase_2")
    jmp(pin, "phase_2") .side(0)
    label("phase_3")
    jmp(pin, "phase_3") .side(1)
    label("phase_4")
    jmp(pin, "phase_4") .side(0)
    label("phase_5")
    jmp(pin, "phase_5") .side(1)
    label("phase_6")
    jmp(pin, "phase_6") .side(0)
    label("phase_7")
    jmp(pin, "phase_7") .side(1)
    label("phase_8")
    jmp(pin, "phase_8") .side(0)
    label("phase_9")
    jmp(pin, "phase_9") .side(1)        # latest seen = 'top'

    wrap()


@rp2.asm_pio(set_init=[rp2.PIO.OUT_LOW], out_init=[rp2.PIO.OUT_LOW])

def toggle_pin():
    wrap_target()
    mov(pins, invert(pins))
    wrap()


# Purge the TX-FIFO and preset the interrupts/X-register

@rp2.asm_pio(autopull=True,
             fifo_join=rp2.PIO.JOIN_TX, out_shiftdir=rp2.PIO.SHIFT_RIGHT)

def irig_fifo_purge():
    irq(clear, rel(0))
    irq(clear, 4)
    set(x, 8)					    # for FIFO: 100 bits = (9 * 11) + 1

    set(y, 2)                       # for ENC

    wrap_target()
    out(null, 2)
    wrap()


# Optimized implementation - only error check 1st 'Out()' of next frame(s),
# as you'd have to be daft to start without filling the first frame.
# Runs at reduced clock = irig_clk * 2 = 2Khz (20 steps per symbol)

@rp2.asm_pio(out_init=[rp2.PIO.OUT_LOW, rp2.PIO.OUT_HIGH], autopull=True,
             fifo_join=rp2.PIO.JOIN_TX, out_shiftdir=rp2.PIO.SHIFT_RIGHT)

def irig_fifo():
    #irq(clear, 4)
    set(x, 8)					    # FIFO 100 bits = (9 * 11) + 1

    out(pins, 2)					# Preload first bit-pair for better timing

    #wait(1, irq, 4)					# Wait for Sync'ed start, then clear IRQ

    label("outer")
    set(y, 9) [16]                  # (loop for 10) + 1 extra = 11

    label("inner")
    out(pins, 2)					# output bit-pair
    jmp(y_dec, "inner") [18]

    out(pins, 2)					# output extra/last bit-pair
    jmp(x_dec, "outer")

    set(x, 8) [15]
    out(null, 24)     				# clear out unused-bits section of ISR
    out(pins, 2) [1]                # output first bit-pair of frame
    jmp(not_osre, "outer")

    irq(rel(0))                     # UNDERFLOW - when Python fails to fill FIFOs
    wrap_target()                   # set IRQ to warn other StateMachines
    set(pins, 0)
    wrap()


# Minimal implementation to fit in RP2040 - don't check for Underflow error
# Note: Requires 'purge' to set X first

@rp2.asm_pio(out_init=[rp2.PIO.OUT_LOW, rp2.PIO.OUT_HIGH], autopull=True,
             fifo_join=rp2.PIO.JOIN_TX, out_shiftdir=rp2.PIO.SHIFT_RIGHT)

def irig_fifo_minimal():
    out(pins, 2)					# Preload first bit-pair for better timing
    #wait(1, irq, 4)					# Wait for Sync'ed start, then clear IRQ

    wrap_target()
    label("outer")
    set(y, 9) [16]                  # (loop for 10) + 1 extra = 11

    label("inner")
    out(pins, 2)					# output bit-pair
    jmp(y_dec, "inner") [18]

    out(pins, 2)					# output extra/last bit-pair
    jmp(x_dec, "outer") [1]

    set(x, 8) [15]
    out(null, 24)     				# clear out unused-bits section of ISR
    out(pins, 2) [2]                # output first bit-pair of frame
    wrap()


@rp2.asm_pio(out_init=[rp2.PIO.OUT_LOW])

def irig_dcls():
    wrap_target()
    mov(pins, pins)                         # copy, but adds 1clock delay
    wrap()


# Note: Requires 'purge' to set Y first

@rp2.asm_pio(set_init=[rp2.PIO.OUT_HIGH])

def irig_enc():
    set(x, 3)
    #set(y, 2)

    #wait(1, irq, 4)                         # Wait for Sync'ed start, then clear IRQ
                                            # race condition

    wrap()									# abuse wrap for PPS sync

    label("start-of-symbol")				# loop for 2 x 12 clocks
    set(pins, 1)
    in_(pins, 2)
    mov(y, isr)
 
    wrap_target()
    label("high_cycle_pt2")
    jmp(x_dec, "high_cycle_pt2") [4]
    jmp(not_y, "low_cycle")
 
    set(x, 5) [3]							# add another 3 x 12 clocks
    jmp(y_dec, "high_cycle_pt2")

    label("low_cycle")
    set(pins, 0)
 
    jmp(pin, "low_cycle_continue") [19]		# for 'Pr/Px, 2 * 12 clocks = 24
    mov(y, isr)
    set(x, 16) [1]							# for 'Data 0', 8 * 12 clocks = 96
    jmp(not_y, "low_cycle_pt2")   
    set(x, 6) [3]							# for 'Data 1', 5 * 12 clocks = 60

    label("low_cycle_pt2")
    jmp(x_dec, "low_cycle_pt2") [3]

    label("low_cycle_continue")
    in_(null, 32)							# clear ISR
    set(x, 3)
    jmp("start-of-symbol")


@rp2.asm_pio(sideset_init=[rp2.PIO.IN_HIGH, rp2.PIO.IN_LOW],
         set_init=[rp2.PIO.IN_HIGH, rp2.PIO.IN_LOW])

def irig_ask():
    #wait(1, irq, 4)                         # Wait for Sync'ed start, then clear IRQ
                                            # race condition

    # fall through for faster PPS sync

    label("high_cycle")
    set(pindirs, 0b11) .side(0b11) [3]		# High = High, High
    set(pindirs, 0b11) .side(0b01) [1]		# Zero = Low, High
    set(pindirs, 0b11) .side(0b00) [3]		# Low  = Low, Low

    wrap_target()
    label("start-of-cycle")
    set(pindirs, 0b11) .side(0b01)			# Zero = Low, High
    jmp(pin, "high_cycle")
    set(pindirs, 0b01) .side(0b01) [3]		# high = In-pull Low, High
    set(pindirs, 0b11) .side(0b01) [1]		# Zero = Low, High
    set(pindirs, 0b10) .side(0b00) [3]		# low  = Low, In-Pull High
    #jmp("start-of-cycle")    
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
    data    (4, 0x00000707)     #  0x0C - Align Dividers for SM4/5/6 and Enable SM4/5/6

    # trigger 2 - optional, requires code changes...
    data    (4, 0x50200000)     #  0x10 - Bank 0 - CTRL Register
    data    (4, 0x00000407)     #  0x14 - Align Dividers for SM2 and Enable SM2

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

    sub     (r3, r3, 5)
    sub     (r3, r3, 5)
    ldr     (r0, [r1, 8])       # value from 0x502000ec=SM1_ADDR into r0
    sub     (r0, r0, r3)

    cmp     (r0, 10)            # safety check, should be <= 10
    bgt     (abort)
    cmp     (r0, 0)             # safety check, should be > 0
    ble     (abort)

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
    mov     (r5, 0x19)          # DEBUG: this is SM-0 address 'base+1'
    '''

    # did we enter IRQ handler too late?
    add     (r6, r5, 6)
    '''
    mov     (r6, 0x1f)          # DEBUG: this is SM-0 address 'base+7'
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
    nop     ()                  # spare/delay
    nop     ()                  # spare/delay

    # pre-load trigger 2 values, requires additional 10 cycles
    # note: also need to change loop length in SM-0
    ldr     (r5, [r7, 0x10])    # loads 0x50400000 into r5
    ldr     (r6, [r7, 0x14])    # loads 0x00000F0F into r6
    nop     ()                  # spare/delay
    nop     ()                  # spare/delay
    nop     ()                  # spare/delay
    nop     ()                  # spare/delay
    nop     ()                  # spare/delay
    nop     ()                  # spare/delay

    # --
    # write correcting SM-0 vs SM-1 'phase' with r0 value
    # every increament of 2 adds 8.3ns

    label   (write)

    data    (2, 0x4487)         # add(r15, r15, r0)
    nop     ()                  # never hit

    nop     ()                  # phase-0
    nop     ()
    nop     ()
    nop     ()
    nop     ()
    nop     ()
    nop     ()
    nop     ()
    nop     ()
    nop     ()                  # phase-9

    str     (r4, [r3, 0])       # Trig-1: Reset SM4's DivClock and start it
    str     (r6, [r5, 0])       # Trig-2: Reset SM11/10/9/8 and start them

    # --
    label   (abort)

    #mov     (r0, 0)


@micropython.asm_thumb
def sync_sm(r0, r1):
    mov(r2, 0xf)
    mov(r3, 8)
    lsl(r2, r3)
    str(r2, [r0, 0])
    str(r2, [r1, 0])


def mp_irq_handler(m):
    global core_dis, ret

    #core_dis[mem32[0xd0000000]] = disable_irq()

    '''
    # reset the clock-phases with CLKDIV_RESTART
    mem32[0x50200000] = 0x00000407
    '''
    ret = precision_handler(0)

    #enable_irq(core_dis[mem32[0xd0000000]])

# -----
packed = []
p_phase = 0

def pack(value, count=1, pr = False):
    # Pack pairs into array words ready for FIFOs, low bits first
    global irig_fifo, p_phase
 
    while count:
        if p_phase == 0:
            irig_fifo.append(0)
 
        if not pr:
            irig_fifo[len(irig_fifo)-1] |= (value & 0x01) << (p_phase * 2)
        else:
            irig_fifo[len(irig_fifo)-1] |= 0x02 << (p_phase * 2)
 
        value = value >> 1
        p_phase = (p_phase + 1) & 0x0f	# 16 pairs per 32bit FIFO word
        count -= 1


def pack_clear():
    global irig_fifo, p_phase

    irig_fifo = []
    p_phase = 0


def pack_test(value=0xAA):
    # Pack a frame with a test pattern
    pack_clear()
    pack(0, 1, True)				# Pr
    pack(value, 8)
    for i in range(8):
        pack(0, 1, True)			# P1..8
        pack(0xAA, 9)
    pack(0, 1, True)				# Pr9
    pack(0xCC, 9)
    pack(0, 1, True)				# Pr0


def pack_from_seconds(abs_sec = 0.0):
    # Pack a frame using float 'seconds'
    gm = utime.gmtime(int(abs_sec))
 
    midnight = utime.mktime([gm[0], gm[1], gm[2], \
                0, 0, 0, gm[6], gm[7]])

    # Encoding definition from:
    # https://en.wikipedia.org/wiki/IRIG_timecode
    pack_clear()
    pack(0, 1, True)				# Pr
    pack(gm[5] % 10, 4)			    # Seconds
    pack(0, 1)
    pack(int(gm[5] / 10), 3)

    pack(0, 1, True)				# P1
    pack(gm[4] % 10, 4)			    # Minutes
    pack(0, 1)
    pack(int(gm[4] / 10), 4)

    pack(0, 1, True)				# P2
    pack(gm[3] % 10, 4)			    # Hours
    pack(0, 1)
    pack(int(gm[3] / 10), 4)

    pack(0, 1, True)				# P3
    pack(gm[7], 4)				    # Day of Year
    pack(0, 1)
    pack(gm[7] >> 4, 4)

    pack(0, 1, True)				# P4
    pack(gm[7] >> 8, 2)			    # Day of Year, continued
    pack(0, 3)
    pack(int((abs_sec-int(abs_sec))*10), 4) # Tenths of second

    pack(0, 1, True)				# P5
    pack(gm[0] % 10, 4)			    # Year (00-99)
    pack(0, 1)
    pack(int(gm[0] / 10) % 10, 4)

    # Definitions from:
    # https://en.wikipedia.org/wiki/IEEE_1344
    pack(0, 1, True)				# P6
    pack(0, 9)                      # forcing 'UTC' with no leap seconds
    pack(0, 1, True)				# P7
    pack(0, 1)                      # no 0.5 TZ
    if irig_trigger == IRIG_FAKE:
        pack(0xF, 4)                # quality is 'not-reliable'
    else:
        pack(0, 4)                  # quality is 'no particular accuracy'

    p = 0                           # compute parity
    for i in range(len(irig_fifo)):
        for j in range(16):
            if (irig_fifo[i] >> ((j+1)*2)) & 1:
                p += 1              # ie Pr, P1..9, P0
            else:
                p += (irig_fifo[i] >> (j*2)) & 1
    pack((p & 1), 1)
    pack(0, 3)

    pack(0, 1, True)				# P8
    pack(int(abs_sec-midnight), 9)
    pack(0, 1, True)				# P9
    pack(int(abs_sec-midnight) >> 9, 9)
    pack(0, 1, True)				# P0


#---------------------------------------------

if __name__ == "__main__":
    # Ensure the CPU frequency is optimal
    # ie. does not cause fraction div on StateMachine clocks
    if freq() != cpu_freq:
        freq(cpu_freq)
 
    # preset ASK pins as inputs, with pull resitors set up/down
    Pin(0, Pin.IN, Pin.PULL_UP)
    Pin(1, Pin.IN, Pin.PULL_DOWN)

    # configure the PPS pin
    pps = machine.Pin(18, machine.Pin.IN, machine.Pin.PULL_UP)
 
    if irig_trigger == IRIG_RTC:
        # Start the StateMachines using a 1PPS signal
        # (for now using a RTC chip as our 1PPS reference)
        ds = DS3231(I2C(0, sda=Pin(16), scl=Pin(17)))
        ds.square_wave(freq=ds.FREQ_1)

    # setup the StateMachines, ensuring FIFO is empty and IRQ set
    irig_sm = []
    irig_sm.append(rp2.StateMachine(0, irig_fifo_purge, freq=ext_freq))
    irig_sm.append(rp2.StateMachine(1, irig_fifo_purge, freq=ext_freq))
    irig_sm.append(rp2.StateMachine(2, irig_fifo_purge, freq=ext_freq))
    irig_sm.append(rp2.StateMachine(3, irig_fifo_purge, freq=ext_freq))
    irig_sm.append(rp2.StateMachine(4, irig_fifo_purge, freq=ext_freq))
    irig_sm.append(rp2.StateMachine(5, irig_fifo_purge, freq=ext_freq))
    irig_sm.append(rp2.StateMachine(6, irig_fifo_purge, freq=ext_freq))
    irig_sm.append(rp2.StateMachine(7, irig_fifo_purge, freq=ext_freq))
    for m in range(len(irig_sm)):
        irig_sm[m].active(1)
    utime.sleep(0.5)
    rp2.PIO(0).remove_program()
    rp2.PIO(1).remove_program()

    # On PIO Block-1
    irig_sm = []
    irig_sm.append(rp2.StateMachine(0, precision_12k, freq=int(cpu_freq / 10), \
                            set_base=Pin(8)))

    # DEBUG - deliberately cause SM-1 and SM-0 wildly different sync's
    utime.sleep(random())

    if irig_polarity == IRIG_PPS_RISING:
        irig_sm.append(rp2.StateMachine(1, start_from_pin_rising, freq=cpu_freq, \
                            set_base=Pin(7), sideset_base=Pin(7),\
                            in_base=Pin(18), jmp_pin=Pin(8)))
    else:
        irig_sm.append(rp2.StateMachine(1, start_from_pin_falling, freq=cpu_freq, \
                            set_base=Pin(7), sideset_base=Pin(7),\
                            in_base=Pin(18), jmp_pin=Pin(8)))

    fifo_sm = len(irig_sm)
    '''
    irig_sm.append(rp2.StateMachine(2, irig_fifo, freq=irig_freq * 2, \
                        out_base=Pin(3), jmp_pin=Pin(4)))
    '''
    irig_sm.append(rp2.StateMachine(2, irig_fifo_minimal, freq=irig_freq * 2, \
                        out_base=Pin(3), jmp_pin=Pin(4)))

    # On PIO Block-2
    irig_sm.append(rp2.StateMachine(4, irig_dcls, freq=irig_freq * 12, \
                        in_base=Pin(5), out_base=Pin(6)))
    irig_sm.append(rp2.StateMachine(5, irig_enc, freq=irig_freq * 12, \
                        set_base=Pin(5), in_base=Pin(3), \
                        jmp_pin=Pin(4)))
    irig_sm.append(rp2.StateMachine(6, irig_ask, freq=irig_freq * 12, \
                        sideset_base=Pin(0), set_base=Pin(0), \
                        jmp_pin=Pin(5)))
    '''
    # DEBUG
    irig_sm.append(rp2.StateMachine(4, toggle_pin, freq=irig_freq * 12, \
                            set_base=Pin(6), in_base=Pin(6), out_base=Pin(6)))
    '''

    # enable the IRQ handler, which will start SM-2/4/5/6
    irig_sm[0].irq(handler=precision_handler, hard=True)
    #irig_sm[0].irq(handler=mp_irq_handler, hard=True)
    utime.sleep(0.1)

    # re-align the clock-phases with CLKDIV_RESTART
    #sync_sm(0x50300000, 0x50200000)          # Block-2 first as more timing critical

    # Pre-fill the entry in FIFO
    if irig_sm[fifo_sm].tx_fifo() < 1:
        #pack_test()
        pack_from_seconds(irig_seconds)

        for p in irig_fifo:
            irig_sm[fifo_sm].put(p)
        irig_seconds += (1000 / irig_freq)

    print("State Machines armed, start scope now :-)")
    utime.sleep(5)
 
    # ---
    # Test section: 
    # Enable SM1/0 which will detect 1PPS
    mem32[0x50200000] = 0x00000003
    print("Go...")
    utime.sleep(0.1)

    # loop, waiting for a successful trigger
    while True:
        if irig_trigger == IRIG_FAKE:
            # Start the StateMachines asserting (fake) 1PPS low
            pps = machine.Pin(18, machine.Pin.OUT, value=0)
            utime.sleep(0.1)
            pps = machine.Pin(18, machine.Pin.IN, machine.Pin.PULL_UP)

        utime.sleep(0.1)
        if (mem32[0x50300000] & (1 << 0)):
            print("IRIG running...")

            # Stop SM-0 & SM-1, but leave SM-2 running
            mem32[0x50200000] = 0x00000004
            break

        #print("try, try again...")#0x%8.8x" % ret)

        # stop SM-4 and loop to trigger again
        #mem32[0x50300000] = 0x00000000


    # Loop, filling the FIFO as needed
    count = 0
    while not irig_fail:
        if irig_sm[fifo_sm].tx_fifo() < 1:
            pack_from_seconds(irig_seconds)
            irig_seconds += (1000 / irig_freq)
            '''
            pack_test(count)
            count = (count + 1) & 0xFF
            '''

            for p in irig_fifo:
                irig_sm[fifo_sm].put(p)
            print(".", end="")
        utime.sleep(0.001)

    print("IRIG complete/aborted")

