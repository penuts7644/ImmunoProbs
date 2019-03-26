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


"""Commandline tool for generating V(D)J sequences from and IGoR model."""


import os
import sys

from halo import Halo
import pandas

from immuno_probs.cdr3.olga_container import OlgaContainer
from immuno_probs.model.default_models import get_default_model_file_paths
from immuno_probs.model.igor_interface import IgorInterface
from immuno_probs.model.igor_loader import IgorLoader
from immuno_probs.util.cli import dynamic_cli_options
from immuno_probs.util.conversion import nucleotides_to_aminoacids
from immuno_probs.util.constant import get_num_threads, get_working_dir, get_separator, get_output_name
from immuno_probs.util.exception import ModelLoaderException, GeneIdentifierException, OlgaException
from immuno_probs.util.io import read_csv_to_dataframe, write_dataframe_to_csv, preprocess_csv_file


class GenerateSeqs(object):
    """Commandline tool for generating sequences from and IGoR model.

    Parameters
    ----------
    subparsers : ArgumentParser
        A subparser object for appending the tool's parser and options.

    Methods
    -------
    run(args)
        Uses the given Namespace commandline arguments for generating sequences.

    """
    def __init__(self, subparsers):
        super(GenerateSeqs, self).__init__()
        self.subparsers = subparsers
        self._add_options()

    def _add_options(self):
        """Function for adding the parser and options to the given ArgumentParser.

        Notes
        -----
            Uses the class's subparser object for appending the tool's parser
            and options.

        """
        # Create the description and options for the parser.
        description = "Generate VDJ or VJ sequences given a custom IGoR " \
            "model (or build-in) by executing IGoR's commandline tool via " \
            "python subprocess. Or generate CDR3 sequences by using the OLGA."
        parser_options = {
            '-model': {
                'type': 'str',
                'choices': ['tutorial-model', 'human-t-alpha', 'human-t-beta',
                            'human-b-heavy', 'mouse-t-beta'],
                'required': '-custom-model' not in sys.argv,
                'help': "Specify a pre-installed model for generation. " \
                        "(required if --custom-model not specified) " \
                        "(select one: %(choices)s)."
            },
            '-type': {
                'type': 'str',
                'choices': ['alpha', 'beta', 'light', 'heavy'],
                'required': ('-custom-model' in sys.argv),
                'help': 'The type of model to create. (select one: ' \
                        '%(choices)s) (required for -custom_model).'
            },
            '-anchor': {
                'metavar': ('<gene>', '<csv>'),
                'type': 'str',
                'action': 'append',
                'nargs': 2,
                'required': ('-cdr3' in sys.argv and '-custom-model' in sys.argv),
                'help': 'A gene (V or J) followed by a CDR3 anchor CSV file. ' \
                        'Note: need to contain gene in the firts column, ' \
                        'anchor index in the second and gene function in the ' \
                        'third (required for -cdr3 and -custom_model).'
            },
            '-custom-model': {
                'metavar': ('<parameters>', '<marginals>'),
                'type': 'str',
                'nargs': 2,
                'help': 'A IGoR parameters txt file followed by an IGoR ' \
                        'marginals txt file.'
            },
            '-generate': {
                'type': 'int',
                'nargs': '?',
                'default': 1,
                'help': 'The number of sequences to generate. (default: ' \
                        '%(default)s)'
            },
            '-cdr3': {
                'action': 'store_true',
                'help': 'If specified, CDR3 sequences are generated, else ' \
                        'V(D)J full length sequences.'
            },
        }

        # Add the options to the parser and return the updated parser.
        parser_tool = self.subparsers.add_parser(
            'generate-seqs', help=description, description=description)
        parser_tool = dynamic_cli_options(parser=parser_tool,
                                          options=parser_options)

    @staticmethod
    def _process_realizations(data, model):
        """Function for processing an IGoR realization dataframe with indices.

        Parameters
        ----------
        data : pandas.DataFrame
            A pandas dataframe object with the IGoR realization data.
        model : IgorLoader
            Object containing the IGoR model.

        Returns
        -------
        pandas.DataFrame
            A pandas dataframe object with 'seq_index', 'gene_choice_v',
            'gene_choice_j' and optionally 'gene_choice_d' columns containing
            the names of the selected genes.

        """
        # If the suplied model is VDJ, locate important columns and update index values.
        if model.get_type() == "VDJ":
            real_df = pandas.concat([data[['seq_index']],
                                     data.filter(regex=("GeneChoice_V_gene_.*")),
                                     data.filter(regex=("GeneChoice_J_gene_.*")),
                                     data.filter(regex=("GeneChoice_D_gene_.*"))],
                                    ignore_index=True, axis=1, sort=False)
            real_df.columns = ['seq_index', 'gene_choice_v', 'gene_choice_j', 'gene_choice_d']
            real_df['gene_choice_v'], real_df['gene_choice_j'], real_df['gene_choice_d'] = zip(
                *real_df.apply(lambda row: (
                    model.get_genomic_data().genV[int(row['gene_choice_v'].strip('()'))][0],
                    model.get_genomic_data().genJ[int(row['gene_choice_j'].strip('()'))][0],
                    model.get_genomic_data().genD[int(row['gene_choice_d'].strip('()'))][0]
                ), axis=1))

        # Or do the same if the model is VJ.
        elif model.get_type() == "VJ":
            real_df = pandas.concat([data[['seq_index']],
                                     data.filter(regex=("GeneChoice_V_gene_.*")),
                                     data.filter(regex=("GeneChoice_J_gene_.*"))],
                                    ignore_index=True, axis=1, sort=False)
            real_df.columns = ['seq_index', 'gene_choice_v', 'gene_choice_j']
            real_df['gene_choice_v'], real_df['gene_choice_j'] = zip(
                *real_df.apply(lambda row: (
                    model.get_genomic_data().genV[int(row['gene_choice_v'].strip('()'))][0],
                    model.get_genomic_data().genJ[int(row['gene_choice_j'].strip('()'))][0]
                ), axis=1))
        return real_df

    def run(self, args, output_dir):
        """Function to execute the commandline tool.

        Parameters
        ----------
        args : Namespace
            Object containing our parsed commandline arguments.
        output_dir : str
            A directory path for writing output files to.

        """
        # If the given type of sequences generation is not CDR3, use IGoR.
        if not args.cdr3:

            # Add general igor commands and setup spinner.
            command_list = []
            working_dir = get_working_dir()
            command_list.append(['set_wd', working_dir])
            command_list.append(['threads', str(get_num_threads())])
            spinner = Halo(text='Building IGoR command', spinner='dots')

            # Add the model (build-in or custom) command.
            spinner.start()
            if args.model:
                files = get_default_model_file_paths(name=args.model)
                command_list.append(['set_custom_model', files['parameters'],
                                     files['marginals']])
            elif args.custom_model:
                command_list.append(['set_custom_model', str(args.custom_model[0]),
                                     str(args.custom_model[1])])

            # Add generate command.
            command_list.append(['generate', str(args.generate), ['noerr']])

            # Execute IGoR through command line and catch error code.
            igor_cline = IgorInterface(args=command_list)
            spinner.succeed()
            exit_code, _, _, _ = igor_cline.call()
            if exit_code != 0:
                print("An error occurred during execution of IGoR " \
                      "command (exit code {})".format(exit_code))
                return

            # Merge the generated output files together (translated).
            spinner.start('Processing sequence realizations')
            sequence_df = read_csv_to_dataframe(
                file=os.path.join(working_dir, 'generated', 'generated_seqs_noerr.csv'),
                separator=';')
            sequence_df['aa_sequence'] = sequence_df['nt_sequence'].apply(nucleotides_to_aminoacids)
            realizations_df = read_csv_to_dataframe(
                file=os.path.join(working_dir, 'generated', 'generated_realizations_noerr.csv'),
                separator=';')
            if args.model:
                files = get_default_model_file_paths(name=args.model)
                model_type = files['type']
                model = IgorLoader(model_type=model_type,
                                   model_params=files['parameters'],
                                   model_marginals=files['marginals'])
            elif args.custom_model:
                model_type = args.type
                model = IgorLoader(model_type=model_type,
                                   model_params=args.custom_model[0],
                                   model_marginals=args.custom_model[1])
            realizations_df = self._process_realizations(data=realizations_df,
                                                         model=model)
            full_seqs_df = sequence_df.merge(realizations_df, on='seq_index')
            spinner.succeed()

            # Write the pandas dataframe to a CSV file.
            spinner.start('Writting file')
            output_filename = get_output_name()
            if not output_filename:
                output_filename = 'generated_seqs_{}'.format(model_type)
            _, _ = write_dataframe_to_csv(
                dataframe=full_seqs_df,
                filename=output_filename,
                directory=output_dir,
                separator=get_separator())
            spinner.succeed()

        # If the given type of sequences generation is CDR3, use OLGA.
        elif args.cdr3:

            # Get the working directory and setup teh spinner.
            working_dir = get_working_dir()
            spinner = Halo(text='Loading model', spinner='dots')

            # Load the model, create the sequence generator and generate the sequences.
            spinner.start()
            try:
                if args.model:
                    files = get_default_model_file_paths(name=args.model)
                    model_type = files['type']
                    model = IgorLoader(model_type=model_type,
                                       model_params=files['parameters'],
                                       model_marginals=files['marginals'])
                    model.set_anchor(gene='V', file=files['v_anchors'])
                    model.set_anchor(gene='J', file=files['j_anchors'])
                elif args.custom_model:
                    model_type = args.type
                    model = IgorLoader(model_type=model_type,
                                       model_params=args.custom_model[0],
                                       model_marginals=args.custom_model[1])
                    for gene in args.anchor:
                        anchor_file = preprocess_csv_file(
                            os.path.join(working_dir, 'cdr3_anchors'), str(gene[1]),
                            get_separator(), ',')
                        model.set_anchor(gene=gene[0], file=anchor_file)
                model.initialize_model()
                spinner.succeed()
            except (ModelLoaderException, GeneIdentifierException) as err:
                spinner.fail(str(err))
                return

            # Setup the sequence generator and generate sequences.
            spinner.start('Generating sequences')
            try:
                seq_generator = OlgaContainer(igor_model=model)
                cdr3_seqs_df = seq_generator.generate(num_seqs=args.generate)
                spinner.succeed()
            except OlgaException as err:
                spinner.fail(str(err))
                return

            # Write the pandas dataframe to a CSV file with.
            spinner.start('Writting file')
            output_filename = get_output_name()
            if not output_filename:
                output_filename = 'generated_seqs_{}_CDR3'.format(model_type)
            _, _ = write_dataframe_to_csv(
                dataframe=cdr3_seqs_df,
                filename=output_filename,
                directory=output_dir,
                separator=get_separator())
            spinner.succeed()


def main():
    """Function to be called when file executed via terminal."""
    print(__doc__)


if __name__ == "__main__":
    main()
