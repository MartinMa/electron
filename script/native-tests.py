#!/usr/bin/env python

import argparse
import os
import subprocess
import sys

SOURCE_ROOT = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
VENDOR_DIR = os.path.join(SOURCE_ROOT, 'vendor')
PYYAML_LIB_DIR = os.path.join(VENDOR_DIR, 'pyyaml', 'lib')
sys.path.append(PYYAML_LIB_DIR)
import yaml  #pylint: disable=wrong-import-position,wrong-import-order


class Command:
  LIST = 'list'
  RUN = 'run'

def parse_args():
  parser = argparse.ArgumentParser(description='Run Google Test binaries')

  parser.add_argument('command',
                      choices=[Command.LIST, Command.RUN],
                      help='command to execute')

  parser.add_argument('-b', '--binary', nargs='*', required=False,
                      help='names of binaries to run')
  parser.add_argument('-c', '--config', required=True,
                      help='path to a tests config')
  parser.add_argument('-t', '--tests-dir', required=False,
                      help='path to a directory with binaries to run')
  parser.add_argument('-o', '--output-dir', required=False,
                      help='path to a folder to save tests results')

  args = parser.parse_args()

  # Additional checks.
  if args.command == Command.RUN and args.tests_dir is None:
    parser.error("specify a path to a dir with test binaries via --tests-dir")

  # Absolutize and check paths.
  # 'config' must exist and be a file.
  args.config = os.path.abspath(args.config)
  if not os.path.isfile(args.config):
    parser.error("file '{}' doesn't exist".format(args.config))

  # 'tests_dir' must exist and be a directory.
  if args.tests_dir is not None:
    args.tests_dir = os.path.abspath(args.tests_dir)
    if not os.path.isdir(args.tests_dir):
      parser.error("directory '{}' doesn't exist".format(args.tests_dir))

  # 'output_dir' must exist and be a directory.
  if args.output_dir is not None:
    args.output_dir = os.path.abspath(args.output_dir)
    if not os.path.isdir(args.output_dir):
      parser.error("directory '{}' doesn't exist".format(args.output_dir))

  return args


def main():
  args = parse_args()
  tests_list = TestsList(args.config, args.tests_dir)

  if args.command == Command.LIST:
    all_binaries_names = tests_list.get_names()
    print '\n'.join(all_binaries_names)
    return 0

  if args.command == Command.RUN:
    if args.binary is not None:
      return tests_list.run(args.binary, args.output_dir)
    else:
      return tests_list.run_all(args.output_dir)

  raise Exception("unexpected command '{}'".format(args.command))


class TestsList():
  def __init__(self, config_path, tests_dir):
    self.config_path = config_path
    self.tests_dir = tests_dir

    # A dict with binary names (e.g. 'base_unittests') as keys
    # and various test data as values of dict type.
    self.tests = self.__get_tests_list(config_path)

  def __len__(self):
    return len(self.tests)

  def get_names(self):
    return self.tests.keys()

  def run(self, binaries, output_dir=None):
    # First check that all names are present in the config.
    for binary_name in binaries:
      if not binary_name in self.tests:
        raise Exception("binary '{0}' not found in config '{1}'".format(
            binary_name, self.config_path))

    suite_returncode = 0

    for binary_name in binaries:
      test_returncode = self.__run(binary_name, output_dir)
      suite_returncode += test_returncode

    return suite_returncode

  def run_only(self, binary_name, output_dir=None):
    return self.run([binary_name], output_dir)

  def run_all(self, output_dir=None):
    return self.run(self.get_names(), output_dir)

  def __get_tests_list(self, config_path):
    tests_list = {}
    config_data = TestsList.__get_config_data(config_path)

    for data_item in config_data['tests']:
      (binary_name, test_data) = TestsList.__get_test_data(data_item)
      tests_list[binary_name] = test_data

    return tests_list

  @staticmethod
  def __get_config_data(config_path):
    with open(config_path, 'r') as stream:
      return yaml.load(stream)

  @staticmethod
  def __expand_shorthand(data):
    """ Treat a string as {'string_value': None}."""

    if isinstance(data, dict):
      return data

    if isinstance(data, basestring):
      return {data: None}

    assert False, "unexpected shorthand type: {}".format(type(data))

  @staticmethod
  def __get_test_data(data_item):
    data_item = TestsList.__expand_shorthand(data_item)

    binary_name = data_item.keys()[0]
    test_data = {
      'excluded_tests': None,
      'platforms': None
    }

    configs = data_item[binary_name]
    if configs is not None:
      # List of excluded tests.
      if 'to_fix' in configs:
        test_data.excluded_tests = configs['to_fix']

      # List of platforms to run the tests on.
      # TODO(alexeykuzmin): Respect the "platform" setting.

    return (binary_name, test_data)

  def __run(self, binary_name, output_dir):
    binary_path = os.path.join(self.tests_dir, binary_name)
    test_binary = TestBinary(binary_path)

    test_data = self.tests[binary_name]
    excluded_tests = test_data['excluded_tests']

    output_file_path = TestsList.__get_output_path(binary_name, output_dir)

    return test_binary.run(excluded_tests=excluded_tests,
                           output_file_path=output_file_path)

  @staticmethod
  def __get_output_path(binary_name, output_dir=None):
    if output_dir is None:
      return None

    return os.path.join(output_dir, "results_{}.xml".format(binary_name))


class TestBinary():
  def __init__(self, binary_path):
    self.binary_path = binary_path

    # Is only used when writing to a file.
    self.output_format = 'xml'

  def run(self, excluded_tests=None, output_file_path=None):
    gtest_filter = ""
    if excluded_tests is not None and len(excluded_tests) > 0:
      excluded_tests_string = TestBinary.__format_excluded_tests(
          excluded_tests)
      gtest_filter = "--gtest_filter={}".format(excluded_tests_string)

    gtest_output = ""
    if output_file_path is not None:
      gtest_output = "--gtest_output={0}:{1}".format(self.output_format,
                                                     output_file_path)

    args = [self.binary_path, gtest_filter, gtest_output]

    # Suppress stdout if we're writing results to a file.
    stdout = None
    if output_file_path is not None:
      devnull = open(os.devnull, 'w')
      stdout = devnull

    returncode = subprocess.call(args, stdout=stdout)
    return returncode

  @staticmethod
  def __format_excluded_tests(excluded_tests):
    return "-" + ":".join(excluded_tests)


if __name__ == '__main__':
  sys.exit(main())
