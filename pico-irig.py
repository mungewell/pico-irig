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

@rp2.asm_pio()

def start_from_pin_rising():
    wait(0, pin, 0)
    wait(1, pin, 0)

    irq(4)      					# Trigger Sync
    #irq(rel(0))					# set IRQ for ticks_us monitoring


@rp2.asm_pio()

def start_from_pin_falling():
    wait(1, pin, 0)
    wait(0, pin, 0)

    irq(4)      					# Trigger Sync
    #irq(rel(0))					# set IRQ for ticks_us monitoring


# Purge the TX-FIFO and preset the interrupts/X-register

@rp2.asm_pio(autopull=True,
             fifo_join=rp2.PIO.JOIN_TX, out_shiftdir=rp2.PIO.SHIFT_RIGHT)

def irig_fifo_purge():
    irq(clear, rel(0))
    irq(clear, 4)
    set(x, 8)					    # FIFO 100 bits = (9 * 11) + 1

    wrap_target()
    out(null, 2)
    wrap()


# Optimized implementation - only error check 1st 'Out()' of next frame(s),
# as you'd have to be daft to start without filling the first frame.
# Runs at reduced clock = irig_clk * 2 = 2Khz (20 steps per symbol)

@rp2.asm_pio(out_init=[rp2.PIO.OUT_LOW, rp2.PIO.OUT_HIGH], autopull=True,
             fifo_join=rp2.PIO.JOIN_TX, out_shiftdir=rp2.PIO.SHIFT_RIGHT)

def irig_fifo():
    irq(clear, 4)
    set(x, 8)					    # FIFO 100 bits = (9 * 11) + 1

    out(pins, 2)					# Preload first bit-pair for better timing

    wait(1, irq, 4)					# Wait for Sync'ed start, then clear IRQ

    label("outer")
    set(y, 9) [17]                  # (loop for 10) + 1 extra = 11

    label("inner")
    out(pins, 2)					# output bit-pair
    jmp(y_dec, "inner") [18]

    out(pins, 2)					# output extra/last bit-pair
    jmp(x_dec, "outer")

    set(x, 8) [16]
    out(null, 24)     				# clear out unused-bits section of ISR
    out(pins, 2)					# output first bit-pair of frame
    jmp(not_osre, "outer")

    irq(rel(0))                     # UNDERFLOW - when Python fails to fill FIFOs
    wrap_target()                   # set IRQ to warn other StateMachines
    set(pins, 0)
    wrap()


# Minimal implementation - don't check for Underflow error
# Requires 'purge' to set X first

@rp2.asm_pio(out_init=[rp2.PIO.OUT_LOW, rp2.PIO.OUT_HIGH], autopull=True,
             fifo_join=rp2.PIO.JOIN_TX, out_shiftdir=rp2.PIO.SHIFT_RIGHT)

def irig_fifo_minimal():
    out(pins, 2)					# Preload first bit-pair for better timing
    wait(1, irq, 4)					# Wait for Sync'ed start, then clear IRQ

    wrap_target()
    label("outer")
    set(y, 9) [17]                  # (loop for 10) + 1 extra = 11

    label("inner")
    out(pins, 2)					# output bit-pair
    jmp(y_dec, "inner") [18]

    out(pins, 2)					# output extra/last bit-pair
    jmp(x_dec, "outer")

    set(x, 8) [16]
    out(null, 24)     				# clear out unused-bits section of ISR
    out(pins, 2) [1]                # output first bit-pair of frame
    wrap()


@rp2.asm_pio(out_init=[rp2.PIO.OUT_HIGH])

def irig_dcls():
    wrap_target()
    mov(pins, pins)
    wrap()


@rp2.asm_pio(set_init=[rp2.PIO.OUT_HIGH])

def irig_enc():
    set(x, 3)
    set(y, 2)
 
    wait(1, irq, 4)                         # Wait for Sync'ed start, then clear IRQ
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
    wait(1, irq, 4)                         # Wait for Sync'ed start, then clear IRQ
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
def sync_sm(r0, r1):
    mov(r2, 0xf)
    mov(r3, 8)
    lsl(r2, r3)
    str(r2, [r0, 0])
    str(r2, [r1, 0])

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
    fifo_sm = len(irig_sm)
    irig_sm.append(rp2.StateMachine(2, irig_fifo, freq=irig_freq * 2, \
                        out_base=Pin(3), jmp_pin=Pin(4)))
    '''
    irig_sm.append(rp2.StateMachine(2, irig_fifo_minimal, freq=irig_freq * 2, \
                        out_base=Pin(3), jmp_pin=Pin(4)))
    '''

    if irig_polarity == IRIG_PPS_RISING:
        irig_sm.append(rp2.StateMachine(0, start_from_pin_rising, freq=ext_freq, \
                            in_base=Pin(18), jmp_pin=Pin(18)))
    else:
        irig_sm.append(rp2.StateMachine(0, start_from_pin_falling, freq=ext_freq, \
                            in_base=Pin(18), jmp_pin=Pin(18)))

    irig_sm.append(rp2.StateMachine(1, irig_dcls, freq=irig_freq * 12, \
                        in_base=Pin(5), out_base=Pin(6)))

    # On PIO Block-2
    irig_sm.append(rp2.StateMachine(5, irig_enc, freq=irig_freq * 12, \
                        set_base=Pin(5), in_base=Pin(3), \
                        jmp_pin=Pin(4)))
    irig_sm.append(rp2.StateMachine(6, irig_ask, freq=irig_freq * 12, \
                        sideset_base=Pin(0), set_base=Pin(0), \
                        jmp_pin=Pin(5)))

    if irig_polarity == IRIG_PPS_RISING:
        irig_sm.append(rp2.StateMachine(4, start_from_pin_rising, freq=ext_freq, \
                            in_base=Pin(18), jmp_pin=Pin(18)))
    else:
        irig_sm.append(rp2.StateMachine(4, start_from_pin_falling, freq=ext_freq, \
                            in_base=Pin(18), jmp_pin=Pin(18)))

    # re-align the clock-phases with CLKDIV_RESTART
    sync_sm(0x50300000, 0x50200000)          # Block-2 first as more timing critical

    # Pre-start most StateMachines
    mem32[0x50200000] = 0x0000000e
    mem32[0x50300000] = 0x0000000e

    # Pre-fill the entry in FIFO
    if irig_sm[fifo_sm].tx_fifo() < 1:
        pack_test()
        #pack_from_seconds(irig_seconds)

        for p in irig_fifo:
            irig_sm[fifo_sm].put(p)
        irig_seconds += (1000 / irig_freq)

    print("State Machines armed, start scope now :-)")
    utime.sleep(5)
 
    # ---
    # Test section: 
    # Enable the rest of StateMachines
    mem32[0x50200000] = 0x0000000f
    mem32[0x50300000] = 0x0000000f
    print("Go...")

    if irig_trigger == IRIG_FAKE:
        # Start the StateMachines asserting (fake) 1PPS low
        pps = machine.Pin(18, machine.Pin.OUT, value=0)
        utime.sleep(0.1)
        pps = machine.Pin(18, machine.Pin.IN, machine.Pin.PULL_UP)
    # ---
 
    # wait for the trigger to have happen
    while mem32[0x50300030]  & (1 << 4):		# Block-2 IRQ4
        utime.sleep(0.1)
 
    # Loop, filling the FIFO as needed
    print("IRIG running...")
    count = 0
    while not irig_fail:
        if irig_sm[fifo_sm].tx_fifo() < 1:
            '''
            pack_from_seconds(irig_seconds)
            irig_seconds += (1000 / irig_freq)
            '''
            pack_test(count)
            count = (count + 1) & 0xFF

            for p in irig_fifo:
                irig_sm[fifo_sm].put(p)
            print(".", end="")
        utime.sleep(0.001)

    print("IRIG complete/aborted")

