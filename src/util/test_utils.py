#=========================================================================
# test_utils
#=========================================================================
# Simple helper test functions.

from pymtl import *
import collections
import re


class RunTestVectorSimError( Exception ):
  pass


#-------------------------------------------------------------------------
# mk_test_case_table
#-------------------------------------------------------------------------


def mk_test_case_table( raw_test_case_table ):

  # First row in test vectors contains port names

  if isinstance( raw_test_case_table[ 0 ], str ):
    test_param_names = raw_test_case_table[ 0 ].split()
  else:
    test_param_names = raw_test_case_table[ 0 ]

  TestCase = collections.namedtuple( "TestCase", test_param_names )

  ids = []
  test_cases = []
  for row in raw_test_case_table[ 1:]:
    ids.append( row[ 0 ] )
    test_cases.append( TestCase(*row[ 1:] ) )

  return {
      'ids': ids,
      'argnames': ( 'test_params' ),
      'argvalues': test_cases,
  }


#-------------------------------------------------------------------------
# run sim
#-------------------------------------------------------------------------


def run_sim( model, dump_vcd=None, test_verilog=False, max_cycles=5000 ):

  # Setup the model

  model.vcd_file = dump_vcd
  if test_verilog:
    model = TranslationTool( model )
  model.elaborate()

  # Create a simulator

  sim = SimulationTool( model )

  # Reset model

  sim.reset()
  print()

  # Run simulation

  while not model.done() and sim.ncycles < max_cycles:
    sim.print_line_trace()
    sim.cycle()

  # Force a test failure if we timed out

  assert sim.ncycles < max_cycles

  # Extra ticks to make VCD easier to read

  sim.cycle()
  sim.cycle()
  sim.cycle()


#-------------------------------------------------------------------------
# run_test_vector_sim
#-------------------------------------------------------------------------


def run_test_vector_sim( model,
                         test_vectors,
                         dump_vcd=None,
                         test_verilog=False ):

  # First row in test vectors contains port names

  if isinstance( test_vectors[ 0 ], str ):
    port_names = test_vectors[ 0 ].split()
  else:
    port_names = test_vectors[ 0 ]

  # Remaining rows contain the actual test vectors

  test_vectors = test_vectors[ 1:]

  # Setup the model

  model.vcd_file = dump_vcd
  if test_verilog:
    model = TranslationTool( model )
  model.elaborate()

  # Create a simulator

  sim = SimulationTool( model )

  # Reset model

  sim.reset()
  print ""

  for row_num, row in enumerate( test_vectors ):
    for port_name, in_value in zip( port_names, row ):
      if port_name[-1 ] != "*":
        exec ( "model.{}.v = in_value".format( port_name ) )

    sim.eval_combinational()
    sim.print_line_trace()

    for port_name, ref_value in zip( port_names, row ):
      if port_name[-1 ] == "*":
        exec ( "out_value = model.{}".format( port_name[ 0:-1 ] ) )
        if ( ref_value != '?' ) and ( out_value != ref_value ):
          error_msg = """
 run_test_vector_sim received an incorrect value!
  - row number     : {row_number}
  - port name      : {port_name}
  - expected value : {expected_msg}
  - actual value   : {actual_msg}
"""
          raise RunTestVectorSimError(
              error_msg.format(
                  row_number=row_num,
                  port_name=port_name,
                  expected_msg=ref_value,
                  actual_msg=out_value ) )

    # Tick the simulation

    sim.cycle()

  # Extra ticks to make VCD easier to read

  sim.cycle()
  sim.cycle()
  sim.cycle()


#-------------------------------------------------------------------------
# run_rdycall_test_vector_sim
#-------------------------------------------------------------------------


def run_rdycall_test_vector_sim( model,
                                 test_vectors,
                                 dump_vcd=None,
                                 test_verilog=False ):

  # First row in test vectors contains port names

  method_vector = []
  if isinstance( test_vectors[ 0 ], str ):
    method_names = test_vectors[ 0 ].split()
  else:
    method_names = test_vectors[ 0 ]

  if isinstance( test_vectors[ 1 ], str ):
    raw_args = test_vectors[ 1 ].split()
    args = []
    for arg in raw_args:
      if arg == ',':
        args[-1 ] += arg
      elif args and args[-1 ][-1 ] == ',':
        args[-1 ] += arg
      else:
        args += [ arg ]
  else:
    args = test_vectors[ 1 ]

  assert len( args ) == len( method_names )

  for method, param in zip( method_names, args ):
    method_list = {}
    method_list[ 'method_name' ] = method

    if 'arg(' in param:
      a = re.match( r'(.*)arg\(((\w|\s|\,)+)\)', param )
      method_list[ 'arg' ] = [
          arg.strip() for arg in a.group( 2 ).split( "," )
      ]
      method_list[ 'arg_start' ] = 1
    else:
      method_list[ 'arg' ] = []
      method_list[ 'arg_start' ] = -1

    if 'ret(' in param:
      a = re.match( r'(.*)ret\(((\w|\s|\,)+)\)', param )
      method_list[ 'ret' ] = [
          arg.strip() for arg in a.group( 2 ).split( "," )
      ]
      method_list[ 'ret_start' ] = 1
    else:
      method_list[ 'ret' ] = []
      method_list[ 'ret_start' ] = -1

    if 'arg(' in param and 'ret(' in param:
      if param.find( 'arg(' ) < param.find( 'ret(' ):
        method_list[ 'ret_start' ] = 1 + len( method_list[ 'arg' ] )
      else:
        method_list[ 'arg_start' ] = 1 + len( method_list[ 'ret' ] )

    method_vector += [ method_list ]

  # Remaining rows contain the actual test vectors

  test_vectors = test_vectors[ 2:]

  # Setup the model

  model.vcd_file = dump_vcd
  if test_verilog:
    model = TranslationTool( model )
  model.elaborate()

  # Create a simulator

  sim = SimulationTool( model )

  # Reset model

  sim.reset()
  print ""

  # Run the simulation

  row_num = 0
  for row in test_vectors:
    row_num += 1

    # Apply test inputs
    for method, in_value in zip( method_vector, row ):
      assert len( in_value ) == len( method[ 'ret' ] ) + len(
          method[ 'arg' ] ) + 1

      exec ( "if hasattr( model.{}, 'rdy' ): assert model.{}.rdy".format(
          method[ 'method_name' ], method[ 'method_name' ] ) )
      exec ( "model.{}.call.v = in_value[ 0 ]".format(
          method[ 'method_name' ] ) )

      if method[ 'arg_start' ] > 0:
        args = method[ 'arg' ]
        arg_start = method[ 'arg_start' ]
        for i in range( len( method[ 'arg' ] ) ):
          exec ( "model.{}.arg.{}.v = in_value[ arg_start + i ]".format(
              method[ 'method_name' ], method[ 'arg' ][ i ] ) )
      sim.eval_combinational()

    # Evaluate combinational concurrent blocks

    sim.eval_combinational()

    # Display line trace output

    sim.print_line_trace()

    # Check test outputs

    for method, in_value in zip( method_vector, row ):

      if method[ 'ret_start' ] > 0:
        rets = method[ 'ret' ]
        ret_start = method[ 'ret_start' ]
        for i in range( len( method[ 'ret' ] ) ):
          ref_value = in_value[ ret_start + i ]
          if ref_value != '?':
            exec ( "out_value = model.{}.ret.{}.v".format(
                method[ 'method_name' ], method[ 'ret' ][ i ] ) )
            if ref_value != out_value:

              error_msg = """
     run_rdycall_test_vector_sim received an incorrect value!
      - row number     : {row_number}
      - method name    : {method_name}
      - return name    : {ret_name}
      - expected value : {expected_msg}
      - actual value   : {actual_msg}
    """
              raise RunTestVectorSimError(
                  error_msg.format(
                      row_number=row_num,
                      method_name="{}".format( method[ 'method_name' ] ),
                      ret_name="ret.{}".format( method[ 'ret' ][ i ] ),
                      expected_msg=ref_value,
                      actual_msg=out_value ) )

    # Tick the simulation

    sim.cycle()

  # Extra ticks to make VCD easier to read

  sim.cycle()
  sim.cycle()
  sim.cycle()
