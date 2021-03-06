from pymtl import *
from lizard.util.rtl.interface import UseInterface
from lizard.util.rtl import alu
from lizard.util.rtl.lookup_table import LookupTable, LookupTableInterface
from lizard.bitutil import clog2
from lizard.core.rtl.messages import DispatchMsg, ExecuteMsg, AluFunc
from lizard.util.rtl.pipeline_stage import StageInterface, DropControllerInterface
from lizard.core.rtl.forwarder import gen_forwarding_stage
from lizard.core.rtl.kill_unit import PipelineKillDropController
from lizard.core.rtl.controlflow import KillType
from lizard.config.general import *


def ALUInterface():
  return StageInterface(DispatchMsg(), ExecuteMsg())


class ALUStage(Model):

  def __init__(s):
    UseInterface(s, ALUInterface())

    imm_len = DispatchMsg().imm.nbits
    data_len = XLEN

    OP_LUT_MAP = {
        AluFunc.ALU_FUNC_ADD: alu.ALUFunc.ALU_ADD,
        AluFunc.ALU_FUNC_SUB: alu.ALUFunc.ALU_SUB,
        AluFunc.ALU_FUNC_AND: alu.ALUFunc.ALU_AND,
        AluFunc.ALU_FUNC_OR: alu.ALUFunc.ALU_OR,
        AluFunc.ALU_FUNC_XOR: alu.ALUFunc.ALU_XOR,
        AluFunc.ALU_FUNC_SLL: alu.ALUFunc.ALU_SLL,
        AluFunc.ALU_FUNC_SRL: alu.ALUFunc.ALU_SRL,
        AluFunc.ALU_FUNC_SRA: alu.ALUFunc.ALU_SRA,
        AluFunc.ALU_FUNC_SLT: alu.ALUFunc.ALU_SLT,
        AluFunc.ALU_FUNC_AUIPC:
            alu.ALUFunc.ALU_ADD,  # We are just adding to the PC
        AluFunc.ALU_FUNC_LUI: alu.ALUFunc.ALU_OR,
    }

    s.op_lut_ = LookupTable(
        LookupTableInterface(DispatchMsg().alu_msg_func.nbits,
                             alu.ALUFunc.bits), OP_LUT_MAP)

    s.alu_ = alu.ALU(alu.ALUInterface(data_len))
    s.msg_ = Wire(DispatchMsg())
    s.msg_imm_ = Wire(imm_len)

    # PYMTL_BROKEN, cant do msg.src1[:32]
    s.src1_ = Wire(data_len)
    s.src1_32_ = Wire(32)
    s.src2_ = Wire(data_len)
    s.src2_32_ = Wire(32)
    s.imm_ = Wire(data_len)
    s.imm_l20_ = Wire(data_len)

    s.res_ = Wire(data_len)
    s.res_32_ = Wire(32)

    # Connect up lookup table
    s.connect(s.op_lut_.lookup_in_, s.msg_.alu_msg_func)
    s.connect(s.alu_.exec_func, s.op_lut_.lookup_out)

    # Connect to disptach get method
    s.connect(s.msg_, s.process_in_)
    s.connect(s.process_accepted, 1)

    # Connect up alu call
    s.connect(s.alu_.exec_unsigned, s.msg_.alu_msg_unsigned)
    s.connect(s.alu_.exec_call, s.process_call)

    # PYMTL_BROKEN
    s.rs1_ = Wire(data_len)
    s.rs2_ = Wire(data_len)
    s.res_ = Wire(data_len)
    s.res_trunc_ = Wire(data_len)
    s.connect_wire(s.rs1_, s.msg_.rs1)
    s.connect_wire(s.rs2_, s.msg_.rs2)
    s.connect(s.res_, s.alu_.exec_res)

    @s.combinational
    def slice32():
      s.src1_32_.v = s.rs1_[:32]
      s.src2_32_.v = s.rs2_[:32]
      s.res_32_.v = s.res_[:32]

    @s.combinational
    def set_src_res():
      if s.msg_.alu_msg_op32:
        if s.msg_.alu_msg_unsigned or s.msg_.alu_msg_func == AluFunc.ALU_FUNC_SRL:
          s.src1_.v = zext(s.src1_32_, data_len)
          s.src2_.v = zext(s.src2_32_, data_len)
        else:
          s.src1_.v = sext(s.src1_32_, data_len)
          s.src2_.v = sext(s.src2_32_, data_len)

        # If op32 shift w, need to ignore bit 5
        s.src2_[5].v &= not (s.msg_.alu_msg_func == AluFunc.ALU_FUNC_SLL or
                             s.msg_.alu_msg_func == AluFunc.ALU_FUNC_SRL or
                             s.msg_.alu_msg_func == AluFunc.ALU_FUNC_SRA)

        s.res_trunc_.v = zext(s.res_32_,
                              data_len) if s.msg_.alu_msg_unsigned else sext(
                                  s.res_32_, data_len)
      else:
        s.src1_.v = s.rs1_
        s.src2_.v = s.rs2_
        s.res_trunc_.v = s.res_
        if s.msg_.alu_msg_func == AluFunc.ALU_FUNC_AUIPC:
          s.src1_.v = s.msg_.hdr_pc
        elif s.msg_.alu_msg_func == AluFunc.ALU_FUNC_LUI:  # LUI is a special case
          s.src1_.v = 0

    @s.combinational
    def set_inputs():
      # PYMTL_BROKEN: sext, concat, and zext only work with wires and constants
      s.msg_imm_.v = s.msg_.imm
      s.imm_.v = sext(s.msg_imm_, data_len)
      if s.msg_.alu_msg_func == AluFunc.ALU_FUNC_AUIPC or s.msg_.alu_msg_func == AluFunc.ALU_FUNC_LUI:
        s.imm_.v = s.imm_ << 12
      s.alu_.exec_src0.v = s.src1_
      s.alu_.exec_src1.v = s.src2_ if s.msg_.rs2_val else s.imm_

    @s.combinational
    def set_process_out():
      s.process_out.v = 0
      s.process_out.hdr.v = s.msg_.hdr
      s.process_out.result.v = s.res_trunc_
      s.process_out.rd.v = s.msg_.rd
      s.process_out.rd_val.v = s.msg_.rd_val
      s.process_out.areg_d.v = s.msg_.areg_d

  def line_trace(s):
    return s.process_in_.hdr_seq.hex()[2:]


def ALUDropController():
  return PipelineKillDropController(
      DropControllerInterface(ExecuteMsg(), ExecuteMsg(),
                              KillType(MAX_SPEC_DEPTH)))


ALU = gen_forwarding_stage(ALUStage, ALUDropController)
