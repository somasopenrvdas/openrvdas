#!/usr/bin/env python3
"""Listener is a simple, yet relatively self-contained class that
takes a list of one or more Readers, a list of zero or more
Transforms, and a list of zero or more Writers. It calls the Readers
(in parallel) to acquire records, passes those records through the
Transforms (in series), and sends the resulting records to the Writers
(in parallel).

It can be run as a standalone script (try 'listen.py --help' for
details), as well as being used as a class:

    listener = Listener(readers, transforms=[], writers=[],
                        interval=0, check_format=False)

    readers        A single Reader or a list of Readers.

    transforms     A single Transform or a list of zero or more Transforms

    writers        A single Writer or a list of zero or more Writers

    interval       How long to sleep before reading sequential records

    check_format   If True, attempt to check that Reader/Transform/Writer
                   formats are compatible, and throw a ValueError if they
                   are not. If check_format is False (the default) the
                   output_format() of the whole reader will be
                   formats.Unknown.
Sample use:

  listener = Listener(readers=[NetworkReader(':6221'),
                               NetworkReader(':6223')],
                      transforms=[TimestampTransform()],
                      writers=[TextFileWriter('/logs/network_recs'),
                               TextFileWriter(None)],
                      interval=0.2)
  listener.run()

Calling listener.quit() from another thread will cause the run() loop
to exit.

NOTE: for fun, run listen.py as an Ouroboros script, feeding it on its
own output:

   echo x > tmp
   listen.py --file tmp --prefix p --write_file tmp --tail --interval 1 -v -v

"""
import argparse
import logging
import sys
import time

sys.path.append('.')

from logger.readers.composed_reader import ComposedReader
from logger.readers.network_reader import NetworkReader
from logger.readers.serial_reader import SerialReader
from logger.readers.text_file_reader import TextFileReader

from logger.transforms.prefix_transform import PrefixTransform
from logger.transforms.slice_transform import SliceTransform
from logger.transforms.timestamp_transform import TimestampTransform

from logger.writers.composed_writer import ComposedWriter
from logger.writers.network_writer import NetworkWriter
from logger.writers.text_file_writer import TextFileWriter
from logger.writers.logfile_writer import LogfileWriter

################################################################################
class Listener:
  ############################
  def __init__(self, readers, transforms=[], writers=[],
               interval=0, check_format=False):
    self.reader = ComposedReader(readers=readers, check_format=check_format)
    self.writer = ComposedWriter(transforms=transforms, writers=writers,
                                 check_format=check_format)
    self.interval = interval
    self.last_read = 0
    
    self.quit_signalled = False

  ############################
  def quit(self):
    self.quit_signalled = True
    logging.debug('Listener.quit() called')
    
  ############################
  # Read/transform/write until either quit() is called in a separate
  # thread, or ComposedReader returns None, indicating that all its
  # component readers have returned EOF.
  def run(self):
    record = ''
    while not self.quit() and record is not None:
      record = self.reader.read()
      self.last_read = time.time()
      
      logging.debug('ComposedReader read: "%s"', record)
      if record:
        self.writer.write(record)

      if self.interval:
        time_to_sleep = self.interval - (time.time() - self.last_read)
        time.sleep(max(time_to_sleep, 0))

################################################################################
if __name__ == '__main__':
  parser = argparse.ArgumentParser()

  parser.add_argument('--network', dest='network', default=None,
                      help='Comma-separated network addresses to read from')

  parser.add_argument('--file', dest='file', default=None,
                      help='Comma-separated files to read from in parallel. '
                      'Note that wildcards in a filename will be expanded, '
                      'and the resulting files read sequentially. A single '
                      'dash (\'-\') will be interpreted as stdout.')

  parser.add_argument('--serial', dest='serial', default=None,
                      help='Comma-separated serial port spec containing at '
                      'least port=[port], but also optionally baudrate, '
                      'timeout, max_bytes and/or other SerialReader '
                      'parameters.')

  parser.add_argument('--interval', dest='interval', type=float, default=0,
                      help='Number of seconds between reads')

  parser.add_argument('--tail', dest='tail',
                      action='store_true', default=False, help='Do not '
                      'exit after reading file EOF; continue to check for '
                      'additional input.')

  parser.add_argument('--prefix', dest='prefix', default='',
                      help='Prefix each record with this string')

  parser.add_argument('--slice', dest='slice', default='', help='Return '
                      'only the specified (space-separated) fields of a '
                      'text record. Can be comma-separated integer values '
                      'and/or ranges, e.g. "1,3,5:7,-1". Note: zero-base '
                      'indexing, so "1:" means "start at second element.')

  parser.add_argument('--slice_separator', dest='slice_separator', default=' ',
                      help='Field separator for --slice.')

  parser.add_argument('--timestamp', dest='timestamp',
                      action='store_true', default=False,
                      help='Timestamp each record as it is read')

  parser.add_argument('--write_file', dest='write_file', default=None,
                      help='File(s) to write to (empty for stdout)')

  parser.add_argument('--write_logfile', dest='write_logfile', default=None,
                      help='Filename base to write to. A date string that '
                      'corresponds to the timestamped date of each record '
                      'Will be appended to filename, with one file per date.')

  parser.add_argument('--write_network', dest='write_network', default=None,
                      help='Network address(es) to write to')

  parser.add_argument('--check_format', dest='check_format',
                      action='store_true', default=False, help='Check '
                      'reader/transform/writer format compatibility')

  parser.add_argument('-v', '--verbosity', dest='verbosity',
                      default=0, action='count',
                      help='Increase output verbosity')
  args = parser.parse_args()

  LOGGING_FORMAT = '%(asctime)-15s %(message)s'
  logging.basicConfig(format=LOGGING_FORMAT)

  LOG_LEVELS ={0:logging.WARNING, 1:logging.INFO, 2:logging.DEBUG}
  args.verbosity = min(args.verbosity, max(LOG_LEVELS))
  logging.getLogger().setLevel(LOG_LEVELS[args.verbosity])

  readers = []
  if args.file:
    for filename in args.file.split(','):
      readers.append(TextFileReader(file_spec=filename, tail=args.tail))
  if args.network:
    for addr in args.network.split(','):
      readers.append(NetworkReader(addr=addr))

  # SerialReader is a little more complicated than other readers
  # because it can take so many parameters. Use the kwargs trick to
  # pass them all in.
  if args.serial:
    kwargs = {}
    for pair in args.serial.split(','):
      (key, value) = pair.split('=')
      kwargs[key] = value
    readers.append(SerialReader(**kwargs))
  
  transforms = []
  if args.slice:
    transforms.append(SliceTransform(args.slice, args.slice_separator))
  if args.timestamp:
    transforms.append(TimestampTransform())
  if args.prefix:
    transforms.append(PrefixTransform(args.prefix))

  writers = []
  if args.write_file:
    for filename in args.write_file.split(','):
      if filename == '-':
        filename = None
      writers.append(TextFileWriter(filename=filename))
  if args.write_logfile:
    writers.append(LogfileWriter(filebase=args.write_logfile))
  if args.write_network:
    for addr in args.write_network.split(','):
      writers.append(NetworkWriter(addr=addr))

  listener = Listener(readers, transforms, writers,
                      interval=args.interval,
                      check_format=args.check_format)
  listener.run()
