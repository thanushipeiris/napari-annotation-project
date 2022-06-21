import csv
import os
import shutil
from pathlib import Path
import numpy as np
from skimage.io import imsave, imread
import yaml

from qtpy.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout,
QGroupBox, QGridLayout, QListWidget, QPushButton, QFileDialog,
QTabWidget, QLabel, QLineEdit, QScrollArea, QCheckBox, QSpinBox)
from qtpy.QtCore import Qt
from .folder_list_widget import FolderList
from .parameters import Param
from . import project as pr


class ProjectWidget(QWidget):
    """
    Implentation of a napari plugin allowing to handle "projects", i.e. 
    sets of images (from multiple folders), label annotations and regions of interest.

    Parameters
    ----------
    napari_viewer : napari.Viewer
        The napari viewer object.
    """
    
    def __init__(self, napari_viewer):
        super().__init__()
        
        self.viewer = napari_viewer

        self.main_layout = QVBoxLayout()
        self.setLayout(self.main_layout)

        self.tabs = QTabWidget()
        self.main_layout.addWidget(self.tabs)

        # project tab
        self.project = QWidget()
        self._project_layout = QVBoxLayout()
        self.project.setLayout(self._project_layout)
        self.tabs.addTab(self.project, 'Project')

        # project tab
        self.export = QWidget()
        self._export_layout = QVBoxLayout()
        self.export.setLayout(self._export_layout)
        self.tabs.addTab(self.export, 'Export')
        
        # Create file list where to drag and drop files to add to the project
        files_vgroup = VHGroup('Files', orientation='G')
        self._project_layout.addWidget(files_vgroup.gbox)
        self.file_list = FolderList(napari_viewer)
        files_vgroup.glayout.addWidget(self.file_list, 0, 0, 1, 2)
        self.btn_remove_file = QPushButton('Remove selected file')
        files_vgroup.glayout.addWidget(self.btn_remove_file, 1, 0, 1, 2)
        self.check_copy_files = QCheckBox('Copy files to project folder')
        files_vgroup.glayout.addWidget(self.check_copy_files, 2, 0, 1, 2)
        
        # Keep track of the channel selection for annotations
        channel_group = VHGroup('Layer to annotate', orientation='V')
        self._project_layout.addWidget(channel_group.gbox)
        self.sel_channel = QListWidget()
        channel_group.glayout.addWidget(self.sel_channel)
        
        # Create rois of fixed size
        self.check_fixed_roi_size = QCheckBox('Fixed ROI size')
        self._project_layout.addWidget(self.check_fixed_roi_size)
        self.roi_size = QSpinBox(visible=False)
        self.roi_size.setMaximum(10000)
        self.roi_size.setValue(128)
        self._project_layout.addWidget(self.roi_size)
        self.roi_width = QSpinBox(visible=False)
        self.roi_width.setMinimum(1)
        self.roi_width.setValue(1)
        self._project_layout.addWidget(self.roi_width)
        self.btn_add_roi = QPushButton('Add ROI', visible=False)
        self._project_layout.addWidget(self.btn_add_roi)
        
        # Select a folder where to save the project
        self.btn_project_folder = QPushButton("Create project")
        self._project_layout.addWidget(self.btn_project_folder)

        # Save current annotations (this is also done automatically when switching to a new image)
        self.btn_save_annotation = QPushButton("Save annotations")
        self._project_layout.addWidget(self.btn_save_annotation)

        # Load an existing project
        self.btn_load_project = QPushButton("Load project")
        self._project_layout.addWidget(self.btn_load_project)

        # Set names to export images and annotations, typically for deep learning training
        self.names_group = VHGroup('Export names', orientation='G')
        self.names_group.gbox.setMaximumHeight(250)

        self._export_layout.addWidget(self.names_group.gbox)
        
        self.btn_export_folder = QPushButton("Export folder")
        self.display_export_folder, self.scroll_export_folder = scroll_label('No selection.')
        self.names_group.glayout.addWidget(self.scroll_export_folder, 0, 0)
        self.names_group.glayout.addWidget(self.btn_export_folder, 0, 1)

        self.names_group.glayout.addWidget(QLabel('Source folder name'), 1, 0, Qt.AlignTop)
        self._source_folder_name = QLineEdit()
        self._source_folder_name.setText("source")
        self.names_group.glayout.addWidget(self._source_folder_name, 1, 1, Qt.AlignTop)

        self.names_group.glayout.addWidget(QLabel('Source name'), 2, 0, Qt.AlignTop)
        self._source_name = QLineEdit()
        self._source_name.setText("img_")
        self.names_group.glayout.addWidget(self._source_name, 2, 1, Qt.AlignTop)

        self.names_group.glayout.addWidget(QLabel('Target folder name'), 3, 0, Qt.AlignTop)
        self._target_folder_name = QLineEdit()
        self._target_folder_name.setText("target")
        self.names_group.glayout.addWidget(self._target_folder_name, 3, 1, Qt.AlignTop)

        self.names_group.glayout.addWidget(QLabel('Target name'), 4, 0, Qt.AlignTop)
        self._target_name = QLineEdit()
        self._target_name.setText("target_")
        self.names_group.glayout.addWidget(self._target_name, 4, 1, Qt.AlignTop)

        self._keep_original_filename = QCheckBox('Keep original filename as '
                                                 'suffix')
        self._keep_original_filename.setChecked(True)
        self.names_group.glayout.addWidget(self._keep_original_filename)

        self.btn_export_data = QPushButton("Export annotations")
        self._export_layout.addWidget(self.btn_export_data)



        self._add_connections()

        self.export_folder = None
        self.ndim = None
        self.params = None

        # linking 2D rois across z layers to form 3D roi
        self.roi_index_to_stackID = {}
        self.stackID_to_roi_indexes = {}
        self.last_stackID=-1

    def _add_connections(self):
        
        self.file_list.model().rowsInserted.connect(self._on_add_file)
        self.file_list.currentItemChanged.connect(self._on_select_file)
        self.btn_remove_file.clicked.connect(self._on_remove_file)
        self.check_copy_files.stateChanged.connect(self._on_check_copy_files)
        self.sel_channel.currentItemChanged.connect(self._update_channels_param)
        self.check_fixed_roi_size.stateChanged.connect(self._on_fixed_roi_size)
        self.btn_add_roi.clicked.connect(self._on_click_add_roi_fixed)
        self.btn_project_folder.clicked.connect(self._on_click_select_project)
        self.btn_save_annotation.clicked.connect(self.save_annotations)
        self.btn_load_project.clicked.connect(self._on_click_load_project)
        self.btn_export_data.clicked.connect(self._export_data)
        self.btn_export_folder.clicked.connect(self._on_click_select_export_folder)

    def open_file(self):
        """Open file selected in list. Returns True if file was opened."""
        
        # clear existing layers. Suspend roi update while doing so, as 
        # roi layer suppresion would trigger a roi update and copy old rois to
        # the new file
        self.clear_layers()

        # if file list is emtpy stop here
        if self.file_list.currentItem() is None:
            return False
        
        # open image and make sure dimensions match previous images
        image_name = self.file_list.currentItem().text()
        self.viewer.open(Path(image_name))
        if self.ndim is not None:
            newdim = self.viewer.layers[0].data.ndim
            if newdim != self.ndim:
                raise Exception(f"Image dimension changed. Only ndim={self.ndim} accepted.")
        else:
            self.ndim = self.viewer.layers[0].data.ndim

        return True

    def clear_layers(self):
        """Remove all layers from viewer."""
        
        # clear existing layers. Suspend roi update while doing so, as 
        # roi layer suppresion would trigger a roi update and copy old rois to
        # the new file
        if 'rois' in [x.name for x in self.viewer.layers]:
            self.viewer.layers['rois'].events.set_data.disconnect(self._update_roi_param)
        self.viewer.layers.clear()

    def _close_project(self, clear_files=True):
        
        self.viewer.layers.clear()
        self.sel_channel.clear()
        if clear_files:
            self.file_list.clear()

    def _on_remove_file(self):
        """Remove selected file and accompanying rois and annotations"""

        file_index = self._get_current_file()
        self.file_list.takeItem(self.file_list.currentRow())
        self._update_params_file_list()
        self.params.channels.pop(file_index)
        self.params.rois.pop(file_index)

        self.params.roi_index_to_stackID.pop(file_index)
        self.params.stackID_to_roi_indexes.pop(file_index)
        self.params.last_stackID.pop(file_index)

        self.params.save_parameters()
        annotation_file = Path(self._create_annotation_filename_current(file_index))
        if annotation_file.exists():
            annotation_file.unlink()

    def _on_add_file(self, parent, first, last):
        """Update params when adding or removing a file"""
        
        if self.params is None:
            self._on_click_select_project()
        if self.check_copy_files.checkState() == 2:
            file = Path(self.file_list.item(last).text())
            if file.parts[0] != 'images':
                copy_to = Path("images") / file.name
                shutil.copy(file, copy_to)
                self.file_list.item(last).setText(copy_to.as_posix())

        self._update_params_file_list()
        for f in self.params.file_paths:
            if f not in self.params.channels.keys():
                self.params.channels[f] = None
            if f not in self.params.rois.keys():
                self.params.rois[f] = []

            if f not in self.params.roi_index_to_stackID.keys():
                self.params.roi_index_to_stackID[f] = {}
            if f not in self.params.stackID_to_roi_indexes.keys():
                self.params.stackID_to_roi_indexes[f] = {}
            if f not in self.params.last_stackID.keys():
                self.params.last_stackID[f] = -1

        self.params.save_parameters()

    def _on_check_copy_files(self):
        """Update file list adding mode when checkbox is toggled"""

        if self.check_copy_files.checkState() == 2:
            self.file_list.local_copy = True
            if self.params is None:
                self._on_click_select_project()
            os.chdir(self.params.project_path)
            self.file_list.local_folder = Path("images/")
            if not self.file_list.local_folder.exists():
                self.file_list.local_folder.mkdir(parents=True)
            self.params.local_project = True
        else:
            self.file_list.local_copy = False
            self.file_list.local_folder = None
            self.params.local_project = False

    def _update_params_file_list(self):
        """Update params file list when adding or removing a file"""

        self.params.file_paths = []
        if self.file_list.count() == 0:
            self.params.file_paths = None
        else:
            for i in range(self.file_list.count()):
                if self.file_list.item(i).text() not in self.params.file_paths:
                    self.params.file_paths.append(self.file_list.item(i).text())

    def _update_channels_param(self):

        if self.sel_channel.currentItem() is not None:
            self.params.channels[self._get_current_file()] = self.sel_channel.currentItem().text()
            self.params.save_parameters()


    # select all rois in a stack together
    def _select_roi_stack(self):##########################################
        current_selected_roi = self.viewer.layers['rois'].selected_data
        # self.viewer.layer.select?  https://github.com/napari/napari/blob/main/napari/layers/shapes/_shapes_mouse_bindings.py


    def _delete_roi_when_stacks(self, roi_i):###############
        # roi was in 3Dstack - delete dict references and stack from viewer
        index_gap = 1 # spaces indexes > roi_i need to be shifted down
        if roi_i in self.roi_index_to_stackID.keys():
            stackID = self.roi_index_to_stackID[roi_i]
            roi_indexes = self.stackID_to_roi_indexes.pop(stackID)
            # select rois from viewer and delete
            print("rois selected", len(self.viewer.layers['rois'].selected_data))
            #self.viewer.layers['rois'].selected_data = {i-1 if i>roi_i else
            # i for i in roi_indexes}

            # remove from roi index to stackID dict
            for i in sorted(roi_indexes, reverse=True):
                del self.roi_index_to_stackID[i]
                # delete in viewer - keeping in mind indexes might have changed
                if i > roi_i:
                    index_gap+=1
                    self.viewer.layers['rois'].selected_data.add(i-1)
                else:
                    self.viewer.layers['rois'].selected_data.add(i)
            self.viewer.layers['rois'].remove_selected()

        # update indexes > roi_i in dicts
        self.roi_index_to_stackID = {(k-index_gap if k>roi_i else k):v
                                     for k,v in self.roi_index_to_stackID.items()}
        for stackID,roi_indexes in self.stackID_to_roi_indexes.items():
            new_roi_indexes = []
            for i in roi_indexes:
                if i > roi_i:
                    new_roi_indexes.append(i-index_gap)
                else:
                    new_roi_indexes.append(i)
            self.stackID_to_roi_indexes[stackID] = new_roi_indexes

    def _move_stack(self, roi_i):
        print("IN _move_stack()", roi_i)
        #print("viewer rois data", self.viewer.layers['rois'].data)
        moved_roi = self.viewer.layers['rois'].data[roi_i]
        stackID = self.roi_index_to_stackID[roi_i]
        rois_to_change_i = self.stackID_to_roi_indexes[stackID]
        new_xy = moved_roi[:,-2::]
        for i in rois_to_change_i:
            self.viewer.layers['rois'].data[i][:,-2::] = new_xy

    def _first_changed_roi_i(self):
        current_roi_num = len(self.viewer.layers['rois'].data)
        for i in range(current_roi_num):
            #print(i)
            #print("current roi changed:",
            #      list(self.viewer.layers['rois'].data[
            #               i].flatten()))
            #print("old     roi changed:", self.params.rois[
            #    self._get_current_file()][i])

            if not np.array_equal(list(self.viewer.layers['rois'].data[
                                       i].flatten()),
                        self.params.rois[self._get_current_file()][i]):

                return i
        return -1

    def _update_roi_3Dstack(self):
        """
        print("EMIT _roi_moved", self.viewer.layers['rois'].data,
              len(self.viewer.layers['rois'].data),
              len(self.params.rois[self._get_current_file()]))
        """
        current_roi_num = len(self.viewer.layers['rois'].data)
        past_roi_num = len(self.params.rois[self._get_current_file()])

        # there are stacks
        if (len(self.roi_index_to_stackID) > 0):

            # TODO there might be a event specifically for moving, deleting
            #  shapes - would make faster BUT do selecting stack together
            #  first
            # https://github.com/napari/napari/pull/2992
            # roi was moved
            if (current_roi_num == past_roi_num):
                print("first_changed_roi_i", self._first_changed_roi_i())
                first_changed_roi = self._first_changed_roi_i()
                if first_changed_roi >=0:
                    print("(current_roi_num == past_roi_num)")

                    # if ROI is in stack we will move linked ROIs
                    if first_changed_roi in self.roi_index_to_stackID.keys():
                        self._move_stack(first_changed_roi)

            # roi was deleted - must update ROI stack dicts
            elif (current_roi_num < past_roi_num):
                first_changed_roi = self._first_changed_roi_i()
                print("first_changed_roi_i", self._first_changed_roi_i())
                if first_changed_roi>=0:
                    self._delete_roi_when_stacks(first_changed_roi)

    def _update_roi_param(self):#########################
        """Live update rois in the params object and the saved parameters file"""
        rois = [list(x.flatten()) for x in self.viewer.layers['rois'].data]
        rois = [[x.item() for x in y] for y in rois]
        
        self.params.rois[self._get_current_file()] = rois
        self.params.save_parameters()

    def _on_fixed_roi_size(self):
        """Display roi options when fixed roi size is selected"""

        if self.check_fixed_roi_size.isChecked():
            self.roi_size.setVisible(True)
            self.roi_width.setVisible(True)
            self.btn_add_roi.setVisible(True)
        else:
            self.roi_size.setVisible(False)
            self.btn_add_roi.setVisible(False)
            
    def save_roi_to_csv(self, event):
        """Unused roi export function to csv file via pandas"""

        import pandas as pd
        if len(self.viewer.layers['rois'].data) > 0:
            rois = pd.DataFrame([x.flatten() for x in self.viewer.layers['rois'].data])
            rois.to_csv(self._create_annotation_filename_current(extension='_rois.csv'), index=False)
        
    def _roi_to_int_on_mouse_release(self, layer, event):
        """Round roi coordinates to integer on mouse release"""

        yield
        while event.type == 'mouse_move':
            yield
        if event.type == 'mouse_release':
            self.viewer.layers['rois'].data = [np.around(x) for x in self.viewer.layers['rois'].data]
    
    def _on_click_add_roi_fixed(self):#########################
        """Add roi of fixed size to current roi layer"""
        new_rois = []
        current_dim_pos = list(self.viewer.dims.current_step)
        width = self.roi_width.value()
        next_roi_i = len(self.viewer.layers['rois'].data)
        for i in range(-width//2+1,width//2+1):
            current_plane = current_dim_pos.copy()
            current_plane[-3] = current_plane[-3]+i
            new_roi = np.array(current_plane) * np.ones((4, self.ndim))
            new_roi[:, -2::] = np.array([
                [0, 0],
                [0, self.roi_size.value()],
                [self.roi_size.value(), self.roi_size.value()],
                [self.roi_size.value(), 0]])
            new_rois.append(new_roi)

        self.viewer.layers['rois'].add_rectangles(new_rois, edge_color='r',
                                                  edge_width=10)

        if width>1:
            # maintain dictionary that maps roi index to stackID and vice versa
            new_roi_i_list = []
            new_stackID = self.last_stackID+1
            print("viewer rois", len(self.viewer.layers["rois"].data))
            for i in range(next_roi_i, next_roi_i+len(new_rois)):
                self.roi_index_to_stackID[i] = new_stackID
                new_roi_i_list.append(i)
            self.stackID_to_roi_indexes[new_stackID] = new_roi_i_list
            print("stackID_to_roi_indexes", self.stackID_to_roi_indexes)

            self.last_stackID = new_stackID
            self.params.last_stackID = self.last_stackID
            self.param.save_parameters()
        """
        current_dim_pos = self.viewer.dims.current_step
        new_roi = np.array(current_dim_pos)*np.ones((4, self.ndim))
        
        # this changes only the last 2 axes values to box edges
        new_roi[:,-2::] = np.array([
            [0, 0],
            [0, self.roi_size.value()],
            [self.roi_size.value(), self.roi_size.value()],
            [self.roi_size.value(),0]])
        self.viewer.layers['rois'].add_rectangles(new_roi, edge_color='r', edge_width=10)
        """

    def _get_current_param_file_index(self):
        """Get the index of the current file in the list of files."""

        file_index = self.params.file_paths.index(self.file_list.currentItem().text())
        return file_index

    def _get_current_file(self):
        """Get current file as text"""

        file_name = self.file_list.currentItem().text()
        return file_name

    def _on_click_select_project(self, event=None):
        """Select folder where to save rois and annotations."""

        # is triggered by click to create new project, clear files
        # otherwise triggered by first file drag and drop and files should
        # not be cleared
        clear_files = event is not None
        self.save_annotations()
        self._close_project(clear_files=clear_files)            

        project_path = Path(str(QFileDialog.getExistingDirectory(self, "Select folder to store project",options=QFileDialog.DontUseNativeDialog)))
        self.params = pr.create_project(project_path)
        os.chdir(project_path)
        self._on_check_copy_files()

    def _on_click_select_export_folder(self):
        """Interactively select folder where to save annotations and rois"""

        self.export_folder = Path(str(QFileDialog.getExistingDirectory(self, "Select folder for export",options=QFileDialog.DontUseNativeDialog)))
        self.display_export_folder.setText(self.export_folder.as_posix())

    def _add_annotation_layer(self):

        self.viewer.add_labels(
            data=np.zeros((self.viewer.layers[0].data.shape), dtype=np.uint16),
            name='annotations'
            )

    def _add_roi_layer(self):
        
        self.roi_layer = self.viewer.add_shapes(
            ndim = self.viewer.layers[0].data.ndim,
            name='rois', edge_color='red', face_color=[0,0,0,0], edge_width=10)

        self.viewer.layers['rois'].events.set_data.connect(self._update_roi)

        # convert rois to integers whenever drawing is over
        self.roi_layer.mouse_drag_callbacks.append(self._roi_to_int_on_mouse_release)

    def _update_roi(self, event):

        self._update_roi_3Dstack() # whenever you have stacks
        # synchronize roi coordinates with those saved in the params
        self._update_roi_param()

    def _create_annotation_filename_current(self, filename=None, extension='_annot.tif'):
        """Create a path name based on the current file path stem.
        
        Parameters
        ----------
        filename: str or Path
            if None, use the current file name
        extension: str
            suffix of the file name

        Returns
        -------
        complete_name: Path

        """

        #if self.params.project_path.joinpath('annotations') is None:
        #    self._on_click_select_project()
        if filename is None:
            filename = Path(self.file_list.currentItem().text()).stem
        else:
            filename = Path(filename).stem
        complete_name = self.params.project_path.joinpath('annotations', filename + extension)

        return complete_name

    def _on_click_load_project(self, event=None, project_path=None):
        """Load an existing project. The chosen folder needs to contain an
        appropriately formatted Parameters.yml file."""

        # close existing project
        self.save_annotations()
        self._close_project()

        #self.params = Param()
        if project_path is None:
            project_path = Path(str(QFileDialog.getExistingDirectory(self, "Select a project folder to load",options=QFileDialog.DontUseNativeDialog)))
        else:
            project_path = Path(project_path)
        os.chdir(project_path)

        self.params = pr.load_project(project_path)
        for f in self.params.file_paths:
            self.file_list.addItem(f)
        if self.params.local_project:
            self.check_copy_files.setChecked(True)
            

    def save_annotations(self, event=None, filename=None):
        """Save annotations in default location or in the specified location."""

        if 'annotations' in [x.name for x in self.viewer.layers]:    
            data = self.viewer.layers['annotations'].data
            imsave(self._create_annotation_filename_current(filename), data, compress=1, check_contrast=False)

    def _export_data(self, event=None):#####################
        """Export cropped data of the images and the annotations using the rois."""

        def get_filename(filepath):
            return os.path.basename(filepath)[:-4]

        if self.export_folder is None:
            self._on_click_select_export_folder()

        images_path = self.export_folder.joinpath(self._source_folder_name.text())
        if not images_path.exists():
            images_path.mkdir()
        labels_path = self.export_folder.joinpath(self._target_folder_name.text())
        if not labels_path.exists():
            labels_path.mkdir()
        
        image_counter = 0
        fieldnames = ['file_path', 'file_name', 'image_index', 'roi_index',
                      'nD', 'size']
        name_dict = []
        for i in range(self.file_list.count()):
            self.file_list.setCurrentRow(i)
            stacksIDs_processed = []
            roi_index_to_stackID = self.params.roi_index_to_stackID[self.file_list.currentItem().text()]
            print(roi_index_to_stackID)

            for j in range(len(self.viewer.layers['rois'].data)):#######params

                limits = self.viewer.layers['rois'].data[j].astype(int)
                annotations_roi = self.viewer.layers['annotations'].data.copy()
                channel = self.params.channels[self._get_current_file()]######
                image_roi = self.viewer.layers[channel].data.copy()

                # 2D ROI

                if j not in roi_index_to_stackID.keys():
                    print(j, "is 2D roi", self.viewer.layers['rois'].data[j])
                    # if image dimensions is more, take slices from start axes
                    for n in range(self.ndim-2):
                        annotations_roi = annotations_roi[limits[0,n]]
                        image_roi = image_roi[limits[0,n]]

                    annotations_roi = annotations_roi[
                        limits[0,-2]:limits[2,-2],
                        limits[0,-1]:limits[1,-1]
                    ]

                    image_roi = image_roi[
                        limits[0,-2]:limits[2,-2],
                        limits[0,-1]:limits[1,-1]
                    ]

                    filepath = self.file_list.currentItem().text()
                    filename = get_filename(filepath)
                    temp_dict = {
                        'file_path': filepath,
                        'file_name': filename,
                        'image_index': image_counter,
                        'roi_index': f"{j}",
                        "nD": "2D",
                        "size": f"{limits[2, -2]-limits[0, -2]}x"
                                f"{limits[1, -1]-limits[0, -1]}"
                    }

                # 3D ROI
                else:
                    print(j, "is 3D roi")

                    stackID = self.roi_index_to_stackID[j]
                    if stackID in stacksIDs_processed:
                        continue
                    roi_indexes = self.stackID_to_roi_indexes[stackID]
                    z_start = self.viewer.layers['rois'].data[roi_indexes[0]][0, -3].astype(int)
                    z_end = self.viewer.layers['rois'].data[roi_indexes[-1]][0, -3].astype(int) + 1

                    
                    # if image dimensions is more, take slices from start axes
                    for n in range(self.ndim - 3):
                        annotations_roi = annotations_roi[limits[0, n]]
                        image_roi = image_roi[limits[0, n]]
                    
                    annotations_roi = annotations_roi[
                                      z_start:z_end,
                                      limits[0, -2]:limits[2, -2],
                                      limits[0, -1]:limits[1, -1]
                                      ]

                    image_roi = image_roi[
                                z_start:z_end,
                                limits[0, -2]:limits[2, -2],
                                limits[0, -1]:limits[1, -1]
                                ]

                    stacksIDs_processed.append(stackID)
                    if j != roi_indexes[0]:
                        raise Warning("processing ROI in stack that isn't first ROI")### delete this - this is for debugging
                    filepath = self.file_list.currentItem().text()
                    filename = get_filename(filepath)
                    temp_dict = {
                        'file_path': filepath,
                        'file_name': filename,
                        'image_index': image_counter,
                        'roi_index': f"{j}-{roi_indexes[-1]}",
                        "nD": "3D",
                        "size": f"{z_end-z_start}x"
                                f"{limits[2, -2]-limits[0, -2]}x"
                                f"{limits[1, -1]-limits[0, -1]}"
                }

                # add suffix with filename if ticked
                if self._keep_original_filename.isChecked():
                    suffix = f"_{filename}"
                else:
                    suffix = ''

                imsave(images_path.joinpath(f'{self._source_name.text()}'
                                            f'{image_counter}'
                                            f'{suffix}.tiff'),
                       image_roi, check_contrast=False)
                imsave(labels_path.joinpath(f'{self._target_name.text()}'
                                            f'{image_counter}'
                                            f'{suffix}.tiff'),
                       annotations_roi, check_contrast=False)
                image_counter += 1
                name_dict.append(temp_dict)
        
        # export information for rois e.g. from which image they were extracted
        with open(self.export_folder.joinpath('rois_infos.csv'), 'w', encoding='UTF8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(name_dict)

    def _on_select_file(self, current_item, previous_item):
        """Update the viewer with the selected file and its corresponding
        annotations and rois."""

        # when switching from an open file, save the annatations of the previous file
        if previous_item is not None:
            self.save_annotations(filename=previous_item.text())
        
        self.sel_channel.clear()

        # open file and add annotations and roi layers. If no image could 
        # be opened because file list is empty, do nothing.
        success = self.open_file()
        if not success:
            return

        self._add_annotation_layer()
        self._add_roi_layer()

        # create channel choices if open lead to multiple layers opening
        for ch in self.viewer.layers:
            if (ch.name != 'annotations') and (ch.name != 'rois'):
                self.sel_channel.addItem(ch.name)
        
        # if channel selection exists in params, select it
        if self.params.channels[current_item.text()] is not None:
            self.sel_channel.setCurrentItem(self.sel_channel.findItems(self.params.channels[current_item.text()], Qt.MatchExactly)[0])
        else:
            self.sel_channel.setCurrentRow(0)
        
        # add annotations if any exist
        if self._create_annotation_filename_current().exists():
            self.viewer.layers['annotations'].data = imread(self._create_annotation_filename_current())
        
        # add rois if any exist
        if current_item.text() in self.params.rois.keys():
            rois = self.params.rois[current_item.text()]
            rois = [np.array(x).reshape(4,self.ndim) for x in rois]
            self.viewer.layers['rois'].add_rectangles(rois, edge_color='r', edge_width=10)

        # add stack info
        if current_item.text() in self.params.roi_index_to_stackID.keys():
            self.roi_index_to_stackID = self.params.roi_index_to_stackID[current_item.text()]
        else:
            self.roi_index_to_stackID = {}
        if current_item.text() in self.params.stackID_to_roi_indexes.keys():
            self.stackID_to_roi_indexes = self.params.stackID_to_roi_indexes[current_item.text()]
        else:
            self.stackID_to_roi_indexes[f] = {}
        if current_item.text() in self.params.last_stackID.keys():
            self.last_stackID = self.params.last_stackID[current_item.text()]
        else:
            self.last_stackID = -1


class VHGroup():
    """Group box with specific layout
    Parameters
    ----------
    name: str
        Name of the group box
    orientation: str
        'V' for vertical, 'H' for horizontal, 'G' for grid
    """

    def __init__(self, name, orientation='V'):
        self.gbox = QGroupBox(name)
        if orientation=='V':
            self.glayout = QVBoxLayout()
        elif orientation=='H':
            self.glayout = QHBoxLayout()
        elif orientation=='G':
            self.glayout = QGridLayout()
        else:
            raise Exception(f"Unknown orientation {orientation}") 

        self.gbox.setLayout(self.glayout)

def scroll_label(default_text = 'default text'):
    """Create scrollabel label"""

    mylabel = QLabel()
    mylabel.setText('No selection.')
    myscroll = QScrollArea()
    myscroll.setWidgetResizable(True)
    myscroll.setWidget(mylabel)
    return mylabel, myscroll
