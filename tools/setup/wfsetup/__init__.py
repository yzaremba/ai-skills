"""The workflow setup tool: settings now, installation later.

Modules:
    blocks      setup's marked blocks and exact lines in a user's text file
    cli         argument parsing and the one place errors are printed
    commands    one module per command, found by name
    definitions a role's definition for one provider, and its inputs digest
    dictionary  a provider's dictionary: models, efforts, versions, the list
    errors      the error a user can act on, and the exit codes
    fileops     every change to a home or a project: planned, then applied
    fsio        the atomic write, links, and a look at a path
    homes       the providers' homes, whose each path is, the shared clone
    jsonkeys    setup's keys in a user's JSON settings file
    locations   the clone, the user home and the project of a run
    manifest    the install record, and how it writes a path
    modellist   a provider's own model list, beside its dictionary
    paths       what is at a path, asked without a traceback
    profiles    the model and effort a role definition runs with
    render      what render installs, as parts that fill one plan
    roles       a role's source, role.toml
    schema      what a settings file may hold
    settings    the layers, and the effective value of each key
    tomlio      reading and writing TOML
    validate    source validation: every problem of the clone's sources
"""
