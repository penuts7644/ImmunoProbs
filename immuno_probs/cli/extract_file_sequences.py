# Create IGoR models and calculate the generation probability of V(D)J and
# CDR3 sequences. Copyright (C) 2019 Wout van Helvoirt

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.


"""Commandline tool for extracting sequences (and CDR3) from given file."""


import os
import sys

import pandas
import numpy

from immuno_probs.util.cli import dynamic_cli_options, make_colored
from immuno_probs.util.constant import get_config_data
from immuno_probs.util.io import copy_to_dir, preprocess_reference_file, \
write_dataframe_to_separated, read_fasta_as_dataframe, read_separated_to_dataframe
from immuno_probs.vdj.sequence_extractor import SequenceExtractor


class ExtractFileSequences(object):
    """Commandline tool for extracting full and CDR3 sequences from given input.

    Parameters
    ----------
    subparsers : argparse.ArgumentParser
        A subparser object for appending the tool's parser and options.

    Methods
    -------
    run(args)
        Uses the given Namespace commandline arguments to extract the full
        length ( VDJ for productive, unproductive and the total) and CDR3
        sequences from a given data file.

    """
    def __init__(self, subparsers):
        super(ExtractFileSequences, self).__init__()
        self.subparsers = subparsers
        self._add_options()

    def _add_options(self):
        """Function for adding the parser/options to the input ArgumentParser.

        Notes
        -----
            Uses the class constructor's subparser object for appending the
            tool's parser and options.

        """
        # Create the description and options for the parser.
        description = "Extract the full length (VDJ for productive, " \
            "unproductive and the total) and CDR3 sequences from a given " \
            "data file. The VDJ sequences can be used to build a new IGoR " \
            "model and the CDR3 sequences can be evaluated."
        parser_options = {
            '-seqs': {
                'metavar': '<separated>',
                'required': 'True',
                'type': 'str',
                'help': "An input separated data file with sequences to " \
                        "extract using the defined column names."
            },
            '-ref': {
                'metavar': ('<gene>', '<fasta>'),
                'type': 'str',
                'action': 'append',
                'nargs': 2,
                'required': 'True',
                'help': "A gene (V or J) followed by a reference genome " \
                        "FASTA file. Note: the FASTA reference genome files " \
                        "needs to conform to IGMT annotation (separated by " \
                        "'|' character)."
            },
            '-n-random': {
                'type': 'int',
                'nargs': '?',
                'help': "Number of random sequences to use from the given " \
                        "file as subset (default: all sequences)."
            },
            '-use-allele': {
                'action': 'store_true',
                'help': "If specified, the allele information from the " \
                        "resolved gene fields are used to when reconstructing " \
                        "the gene choices (default: allele from config is " \
                        "used for each gene)."
            },
        }

        # Add the options to the parser and return the updated parser.
        parser_tool = self.subparsers.add_parser(
            'extract', help=description, description=description)
        parser_tool = dynamic_cli_options(parser=parser_tool,
                                          options=parser_options)

    @staticmethod
    def _process_gene_df(filename, nt_col, resolved_col):
        """Private function for processing the given gene FASTA file.

        Parameters
        ----------
        filename : str
            File path FASTA of the gene to process.
        nt_col : str
            The column name containing the sequences.
        resolved_col : str
            The column name containing the resolved values.

        """
        # Read in the seperated file as dataframe.
        gene_df = read_fasta_as_dataframe(
            file=filename, col=nt_col, header='info')

        # Modify the dataframe to have gene resolved column, remove the old
        # info column and return.
        gene_df[resolved_col] = pandas.DataFrame(
            list(gene_df['info'].apply(lambda x: x.split('|')[1])))
        gene_df.drop('info', axis=1, inplace=True)
        return gene_df

    def run(self, args, output_dir):
        """Function to execute the commandline tool.

        Parameters
        ----------
        args : Namespace
            Object containing our parsed commandline arguments.
        output_dir : str
            A directory path for writing output files to.

        """
        # Get the working directory.
        working_dir = get_config_data('WORKING_DIR')

        # Collect and read in the corresponding reference genomic templates.
        sys.stdout.write('Processing genomic reference templates...')
        try:
            for gene in args.ref:
                print(gene)
                filename = preprocess_reference_file(
                    os.path.join(working_dir, 'genomic_templates'),
                    copy_to_dir(working_dir, gene[1], 'fasta'),
                )
                if gene[0] == 'V':
                    v_gene_df = self._process_gene_df(
                        filename=filename, nt_col=get_config_data('NT_COL'),
                        resolved_col=get_config_data('V_RESOLVED_COL'))
                if gene[0] == 'J':
                    j_gene_df = self._process_gene_df(
                        filename=filename, nt_col=get_config_data('NT_COL'),
                        resolved_col=get_config_data('J_RESOLVED_COL'))
        except (IOError, KeyError, ValueError) as err:
            sys.stdout.write(make_colored('error\n', 'red'))
            sys.stderr.write(make_colored(str(err) + '\n', 'bg-red'))
            return

        # Read in the sequence data.
        sys.stdout.write('Pre-processing input sequence file...')
        try:
            seqs_df = read_separated_to_dataframe(
                file=args.seqs, separator=get_config_data('SEPARATOR'),
                cols=[get_config_data('NT_COL'),
                      get_config_data('AA_COL'),
                      get_config_data('FRAME_TYPE_COL'),
                      get_config_data('CDR3_LENGTH_COL'),
                      get_config_data('V_RESOLVED_COL'),
                      get_config_data('J_RESOLVED_COL')])

            # Take a random subsample of sequences in the file.
            if args.n_random is not None:
                if args.n_random > 0 and len(seqs_df) >= args.n_random:
                    seqs_df = seqs_df.sample(n=args.n_random, random_state=1)
                else:
                    sys.stdout.write(make_colored('error\n', 'red'))
                    sys.stderr.write(make_colored(
                        'Number of random sequences should be higher 0 and ' \
                        'smaller than total number of rows in file\n', 'bg-red'))
                    return
            sys.stdout.write(make_colored('success\n', 'green'))
        except (IOError, KeyError, ValueError) as err:
            sys.stdout.write(make_colored('error\n', 'red'))
            sys.stderr.write(make_colored(str(err) + '\n', 'bg-red'))
            return

        # Setup the data extractor class and extract data.
        sys.stdout.write('Extracting and reassembling sequences...')
        try:
            cdr3_df = pandas.DataFrame()
            full_prod_df = pandas.DataFrame()
            full_unprod_df = pandas.DataFrame()
            full_df = pandas.DataFrame()
            extractor = SequenceExtractor()
            results = extractor.extract(
                num_threads=get_config_data('NUM_THREADS'),
                seqs=seqs_df,
                ref_v_genes=v_gene_df,
                ref_j_genes=j_gene_df,
                row_id_col=get_config_data('ROW_ID_COL'),
                nt_col=get_config_data('NT_COL'),
                aa_col=get_config_data('AA_COL'),
                frame_type_col=get_config_data('FRAME_TYPE_COL'),
                cdr3_length_col=get_config_data('CDR3_LENGTH_COL'),
                v_resolved_col=get_config_data('V_RESOLVED_COL'),
                v_gene_choice_col=get_config_data('V_GENE_CHOICE_COL'),
                j_resolved_col=get_config_data('J_RESOLVED_COL'),
                j_gene_choice_col=get_config_data('J_GENE_CHOICE_COL'),
                use_allele=args.use_allele,
                default_allele=get_config_data('ALLELE'))
            for processed in results:
                processed[0].insert(0, get_config_data('FILE_NAME_ID_COL'),
                                    os.path.splitext(os.path.basename(args.seqs))[0])
                processed[1].insert(0, get_config_data('FILE_NAME_ID_COL'),
                                    os.path.splitext(os.path.basename(args.seqs))[0])
                processed[2].insert(0, get_config_data('FILE_NAME_ID_COL'),
                                    os.path.splitext(os.path.basename(args.seqs))[0])
                processed[3].insert(0, get_config_data('FILE_NAME_ID_COL'),
                                    os.path.splitext(os.path.basename(args.seqs))[0])
                cdr3_df = cdr3_df.append(processed[0], ignore_index=True)
                full_prod_df = full_prod_df.append(processed[1], ignore_index=True)
                full_unprod_df = full_unprod_df.append(processed[2], ignore_index=True)
                full_df = full_df.append(processed[3], ignore_index=True)
            sys.stdout.write(make_colored('success\n', 'green'))
        except KeyError as err:
            sys.stdout.write(make_colored('error\n', 'red'))
            sys.stderr.write(make_colored(str(err) + '\n', 'bg-red'))
            return

        # Copy the output files to the output directory with prefix.
        sys.stdout.write('Writting files...')
        try:
            output_prefix = get_config_data('OUT_NAME')
            if not output_prefix:
                output_prefix = 'sequence_extract'
            _, filename_1 = write_dataframe_to_separated(
                dataframe=cdr3_df,
                filename='{}_CDR3'.format(output_prefix),
                directory=output_dir,
                separator=get_config_data('SEPARATOR'),
                index_name=get_config_data('I_COL'))
            _, filename_2 = write_dataframe_to_separated(
                dataframe=full_prod_df,
                filename='{}_full_length_productive'.format(output_prefix),
                directory=output_dir,
                separator=get_config_data('SEPARATOR'),
                index_name=get_config_data('I_COL'))
            _, filename_3 = write_dataframe_to_separated(
                dataframe=full_unprod_df,
                filename='{}_full_length_unproductive'.format(output_prefix),
                directory=output_dir,
                separator=get_config_data('SEPARATOR'),
                index_name=get_config_data('I_COL'))
            _, filename_4 = write_dataframe_to_separated(
                dataframe=full_df,
                filename='{}_full_length'.format(output_prefix),
                directory=output_dir,
                separator=get_config_data('SEPARATOR'),
                index_name=get_config_data('I_COL'))
            sys.stdout.write("(written '{}', '{}', '{}' and '{}')...".format(
                filename_1, filename_2, filename_3, filename_4))
            sys.stdout.write(make_colored('success\n', 'green'))
        except IOError as err:
            sys.stdout.write(make_colored('error\n', 'red'))
            sys.stderr.write(make_colored(str(err) + '\n', 'bg-red'))
            return


def main():
    """Function to be called when file executed via terminal."""
    print(__doc__)


if __name__ == "__main__":
    main()
