from pymtl import *
from lizard.bitutil import clog2nz
from lizard.util.rtl.interface import Interface, IncludeSome, UseInterface
from lizard.util.rtl.method import MethodSpec
from lizard.util.rtl.registerfile import RegisterFile, RegisterFileInterface
from lizard.util.rtl.mux import Mux


class SnapshottingRegisterFileInterface(Interface):

  def __init__(s, dtype, nregs, num_read_ports, num_write_ports,
               write_read_bypass, write_snapshot_bypass, nsnapshots):
    # No dump port exposed, so write_dump_snapshot is False
    base = RegisterFileInterface(dtype, nregs, num_read_ports, num_write_ports,
                                 write_read_bypass, False)

    s.SnapshotId = Bits(clog2nz(nsnapshots))
    s.Addr = base.Addr
    s.Data = base.Data

    ordering_chains = [
        s.bypass_chain('write', 'snapshot', write_snapshot_bypass),
    ] + s.successor('restore', ['read', 'write']) + [
        ['snapshot', 'restore', 'set'],
    ]

    super(SnapshottingRegisterFileInterface, s).__init__(
        [
            MethodSpec(
                'snapshot',
                args={
                    'target_id': s.SnapshotId,
                },
                rets=None,
                call=True,
                rdy=False,
            ),
            MethodSpec(
                'restore',
                args={
                    'source_id': s.SnapshotId,
                },
                rets=None,
                call=True,
                rdy=False,
            ),
        ],
        bases=[
            IncludeSome(base, {'read', 'write', 'set'}),
        ],
        ordering_chains=ordering_chains,
    )


class SnapshottingRegisterFile(Model):

  def __init__(s,
               dtype,
               nregs,
               num_read_ports,
               num_write_ports,
               write_read_bypass,
               write_snapshot_bypass,
               nsnapshots,
               reset_values=None):
    UseInterface(
        s,
        SnapshottingRegisterFileInterface(dtype, nregs, num_read_ports,
                                          num_write_ports, write_read_bypass,
                                          write_snapshot_bypass, nsnapshots))

    # Note that write_dump_bypass is set with write_snapshot_bypass
    # To bypass the result of a write into a snapshot, the internal
    # registerfile must dump the result of a write
    s.regs = RegisterFile(
        dtype,
        nregs,
        num_read_ports,
        num_write_ports,
        write_read_bypass,
        write_snapshot_bypass,
        reset_values=reset_values)

    s.snapshots = [
        RegisterFile(dtype, nregs, 0, 0, False, False)
        for _ in range(nsnapshots)
    ]

    # Forward read and writes to register file
    s.connect_m(s.read, s.regs.read)
    s.connect_m(s.write, s.regs.write)

    # Connect the dump data from the primary register file
    # to the set port on each snapshot
    for i in range(nsnapshots):
      for j in range(nregs):
        s.connect(s.snapshots[i].set_in_[j], s.regs.dump_out[j])

      # Write to a given snapshot if it matches the target and snapshot was called
      @s.combinational
      def handle_snapshot_save(i=i):
        s.snapshots[
            i].set_call.v = s.snapshot_call and s.snapshot_target_id == i

    s.snapshot_muxes = [Mux(dtype, nsnapshots) for _ in range(nregs)]
    for j in range(nregs):
      s.connect(s.snapshot_muxes[j].mux_select, s.restore_source_id)
      for i in range(nsnapshots):
        s.connect(s.snapshot_muxes[j].mux_in_[i], s.snapshots[i].dump_out[j])

    # Restore by writing data from the snapshot back into the register file
    # set port.
    # But:
    # (1) If snapshot and restore are called in the same cycle on the same snapshot:
    #  (a) write_snapshot_bypass is False: we snapshot, write, and restore.
    #      It must appear as if the write never happened, so we restore from
    #      s.regs.dump_out
    #  (b) write_snapshot_bypass is True: we write, snapshot, and restore.
    #      It must appear as if the restore never happened, so we do not restore
    # (2) If restore and set are called in the same cycle, the restore doesn't matter.
    #     Execute the set, and do not restore.

    # Compute the restore vector for case 1
    s.restore_vector = [Wire(dtype) for _ in range(nregs)]
    s.should_restore = Wire(1)
    if not write_snapshot_bypass:
      s.connect(s.should_restore, s.restore_call)
      for j in range(nregs):

        @s.combinational
        def compute_restore_vector(j=j):
          if s.snapshot_call and s.restore_call and s.snapshot_target_id == s.restore_source_id:
            s.restore_vector[j].v = s.regs.dump_out[j]
          else:
            s.restore_vector[j].v = s.snapshot_muxes[j].mux_out
    else:

      @s.combinational
      def compute_should_restore():
        if s.snapshot_call and s.restore_call and s.snapshot_target_id == s.restore_source_id:
          s.should_restore.v = 0
        else:
          s.should_restore.v = s.restore_call

      for j in range(nregs):
        s.connect(s.restore_vector[j], s.snapshot_muxes[j].mux_out)

    # Handle the restore-set conflict for case 2
    s.set_vector = [Wire(dtype) for _ in range(nregs)]
    s.should_set = Wire(1)
    s.set_muxes = [Mux(dtype, 2) for _ in range(nregs)]

    @s.combinational
    def handle_should_set():
      s.should_set.v = s.should_restore | s.set_call

    for j in range(nregs):
      s.connect(s.set_muxes[j].mux_in_[0], s.restore_vector[j])
      s.connect(s.set_muxes[j].mux_in_[1], s.set_in_[j])
      s.connect(s.set_muxes[j].mux_select, s.set_call)
      s.connect(s.set_muxes[j].mux_out, s.regs.set_in_[j])

    s.connect(s.regs.set_call, s.should_set)

  def line_trace(s):
    return s.regs.line_trace()
