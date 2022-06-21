from pathlib import Path
from .parameters import Param
import yaml

def create_project(project_path, file_paths=None, channels=None, rois=None,
                   roi_index_to_stackID=None, stackID_to_roi_indexes=None,
                   last_stackID=None):
    """
    Create a project.

    Parameters
    ----------
    project_path : str
        path where the project is saved
    file_paths : list[str]
        list of paths of files belonging to the project
    channels : dict of str
        channel getting exported as source for each file
    rois : dict of arrays
        flat list of rois for each file
    roi_index_to_stackID: dict str:{int:int}
        filepath mapped to roi indexes mapped to stackID
    stackID_to_roi_indexes: dict str:{int: list[int]}
        filepath mapped to stackID to list of roi indexes in that stack
    last_stackID: dict str:int
        filepath mapped to tally of the highest stackID used (for determining
        next stackID)

    Returns
    -------
    project : Project
        project object

    """

    project_path = Path(project_path)
    if not project_path.exists():
        project_path.mkdir()

    if rois is None:
        rois = {}
    if channels is None:
        channels = {}
    if roi_index_to_stackID is None:
        roi_index_to_stackID = {}
    if stackID_to_roi_indexes is None:
        stackID_to_roi_indexes = {}
    if last_stackID is None:
        last_stackID = {}

    project = Param(
        project_path=project_path,
        file_paths=file_paths,
        channels=channels,
        rois=rois,
        roi_index_to_stackID=roi_index_to_stackID,
        stackID_to_roi_indexes=stackID_to_roi_indexes,
        last_stackID=last_stackID
    )

    if not project_path.joinpath('annotations').exists():
        project_path.joinpath('annotations').mkdir()
    project.save_parameters()

    return project

def load_project(project_path):
    """
    Load a project.

    Parameters
    ----------
    project_path : str
        path where the project is saved

    Returns
    -------
    project : Project
        project object

    """

    project = Param()
    project_path = Path(project_path)
    if not project_path.joinpath('Parameters.yml').exists():
        raise FileNotFoundError(f"Project {project_path} does not exist")

    with open(project_path.joinpath('Parameters.yml')) as file:
        documents = yaml.full_load(file)
    for k in documents.keys():
        print("reading yaml", k, documents[k])
        setattr(project, k, documents[k])
    project.project_path = project_path

    return project