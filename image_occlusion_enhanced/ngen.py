# -*- coding: utf-8 -*-
####################################################
##                                                ##
##           Image Occlusion Enhanced             ##
##                                                ##
##        Copyright (c) Glutanimate 2016          ##
##       (https://github.com/Glutanimate)         ##
##                                                ##
##     Original Image Occlusion 2.0 add-on is     ##
##         Copyright (c) 2012-2015 tmbb           ##
##           (https://github.com/tmbb)            ##
##                                                ##
##  --------------------------------------------  ##
##                                                ##
##              ngen.py is based on               ##
##           Simple Picture Occlusion             ##
##                   which is                     ##
##          Copyright (c) 2013 SteveAW            ##
##             (steveawa@gmail.com)               ##
##                                                ##
####################################################

"""
Generates the actual IO notes and writes them to
the collection.
"""

import os
import logging, sys

from aqt.qt import *
from aqt import mw
from aqt.utils import tooltip
from anki.notes import Note

from xml.dom import minidom
from Imaging.PIL import Image
from uuid import uuid
import shutil

from dialogs import ioHelp, ioAskUser
from utils import fname2img
from config import *

# Explanation of some of the variables:
#
# nid:          Note ID set by Anki
# note_id:      Image Occlusion Note ID set as the first field of each IO note
# uniq_id:      Unique sequence of random characters. First part of the note_id
# occl_tp:      Two-letter code that signifies occlusion type. Second part of
#               the note_id
# occl_id:      Combination of uniq_id + occl_tp - unique identifier shared
#               by all notes created in one IO session
# note_nr:      Third part of the note_id

def genByKey(key, old_occl_tp=None):
    """Get note generator based on occl_tp/user input"""
    if key in ["Don't Change"]:
        return genByKey(old_occl_tp, None)
    elif key in ["ao", "Hide All, Reveal One"]:
        return IoGenHideAllRevealOne
    elif key in ["aa", "Hide All, Reveal All"]:
        return IoGenHideAllRevealAll
    elif key in ["oa", "Hide One, Reveal All"]:
        return IoGenHideOneRevealAll
    else:
        return IoGenHideAllRevealOne

class ImgOccNoteGenerator(object):
    def __init__(self, ed, svg, image_path, opref, tags, fields, did):
        self.ed = ed
        self.new_svg = svg
        self.image_path = image_path
        self.opref = opref
        self.tags = tags
        self.fields = fields
        self.did = did
        self.qfill = '#' + mw.col.conf['imgocc']['qfill']
        self.stripattr = ['opacity', 'stroke-opacity', 'fill-opacity']
        loadConfig(self)

    def generateNotes(self):
        """Generate new notes"""
        state = "default"
        self.uniq_id = str(uuid.uuid4()).replace("-","")
        self.occl_id = '%s-%s' % (self.uniq_id, self.occl_tp)

        ( svg_node, layer_node ) = self._getMnodesAndSetIds()
        if not self.mnode_ids:
            tooltip("No cards to generate.<br>\
                Are you sure you set your masks correctly?")
            return False

        self.new_svg = svg_node.toxml() # write changes to svg
        omask_path = self._saveMask(self.new_svg, self.occl_id, "O")
        qmasks = self._generateMaskSVGsFor("Q")
        amasks = self._generateMaskSVGsFor("A")
        img = fname2img(self._addImageToCol())

        mw.checkpoint("Adding Image Occlusion Cards")
        for nr, idx in enumerate(self.mnode_indexes):
            note_id = self.mnode_ids[idx]
            self._saveMaskAndReturnNote(omask_path, qmasks[nr], amasks[nr],
                                        img, note_id)

        parent = None
        tooltip("%s %s <b>added</b>" % self.cardS(len(qmasks)), parent=parent)
        return state

    def updateNotes(self):
        """Update existing notes"""
        state = "default"
        self.uniq_id = self.opref['uniq_id']
        self.occl_id = '%s-%s' % (self.uniq_id, self.occl_tp)
        omask_path = None

        self._findAllNotes()
        ( svg_node, mlayer_node ) = self._getMnodesAndSetIds(True)
        if not self.mnode_ids:
            tooltip("No shapes left. You can't delete all cards.<br>\
                Are you sure you set your masks correctly?")
            return False
        mw.checkpoint("Editing Image Occlusion Cards")
        ret = self._deleteAndIdNotes(mlayer_node)
        if not ret:
            # confirmation window rejected
            return False
        else:
            (del_count, new_count) = ret

        self.new_svg = svg_node.toxml() # write changes to svg
        old_svg = self._getOriginalSvg() # load original svg
        if self.new_svg != old_svg or self.occl_tp != self.opref["occl_tp"]:
            # updated masks or occlusion type
            omask_path = self._saveMask(self.new_svg, self.occl_id, "O")
            qmasks = self._generateMaskSVGsFor("Q")
            amasks = self._generateMaskSVGsFor("A")
            state = "reset"

        old_img = fname2img(self.opref['image'])
        if fname2img(self.image_path) != old_img:
            # updated image
            col_image = self._addImageToCol()
            img = fname2img(col_image)
        else:
            img = old_img

        logging.debug("mnode_indexes %s", self.mnode_indexes)
        for nr, idx in enumerate(self.mnode_indexes):
            logging.debug("=====================")
            logging.debug("nr %s", nr)
            logging.debug("idx %s", idx)
            note_id = self.mnode_ids[idx]
            logging.debug("note_id %s", note_id)
            logging.debug("self.nids %s", self.nids)
            nid = self.nids[note_id]
            logging.debug("nid %s", nid)
            if omask_path:
                self._saveMaskAndReturnNote(omask_path, qmasks[nr], amasks[nr],
                                            img, note_id, nid)
            else:
                self._saveMaskAndReturnNote(None, None, None,
                                            img, note_id, nid)
        self.showUpdateTooltip(del_count, new_count)
        return state

    def cardS(self, cnt):
        s = "card"
        if cnt > 1 or cnt == 0:
            s = "cards"
        return (cnt, s)

    def showUpdateTooltip(self, del_count, new_count):
        upd_count = max(0, len(self.mnode_indexes) - del_count - new_count)
        ttip = "%s old %s <b>edited in place</b>" % self.cardS(upd_count)
        if del_count > 0:
            ttip += "<br>%s existing %s <b>deleted</b>" % self.cardS(del_count)
        if new_count > 0:
            ttip += "<br>%s new %s <b>created</b>" % self.cardS(new_count)
        tooltip(ttip, parent=self.ed.parentWindow)

    def _getOriginalSvg(self):
        """Returns original SVG as a string"""
        mask_doc = minidom.parse(self.opref["omask"])
        svg_node = mask_doc.documentElement
        return svg_node.toxml()

    def layerNodesFrom(self, svg_node):
        """Get layer nodes (topmost group nodes below the SVG node)"""
        assert (svg_node.nodeType == svg_node.ELEMENT_NODE)
        assert (svg_node.nodeName == 'svg')
        layer_nodes = [node for node in svg_node.childNodes
                            if node.nodeType == node.ELEMENT_NODE]
        assert (len(layer_nodes) >= 1)
        # last, i.e. top-most element, needs to be a layer:
        assert (layer_nodes[-1].nodeName == 'g')
        return layer_nodes

    def _getMnodesAndSetIds(self, edit=False):
        """Find mask nodes in masks layer and read/set node IDs"""
        self.mnode_indexes = []
        self.mnode_ids = {}
        mask_doc = minidom.parseString(self.new_svg)
        svg_node = mask_doc.documentElement
        layer_nodes = self.layerNodesFrom(svg_node)
        mlayer_node = layer_nodes[-1] # treat topmost layer as masks layer
        for i, node in enumerate(mlayer_node.childNodes):
            # minidom doesn't offer a childElements method and childNodes
            # also returns whitespace found in the mlayer_node as a child node.
            # For that reason we use self.mnode_indexes to register all
            # indexes of mlayer_node children that contain actual elements,
            # i.e. mask nodes
            if (node.nodeType == node.ELEMENT_NODE) and (node.nodeName != 'title'):
                mnode = mlayer_node.childNodes[i]
                self.mnode_indexes.append(i)
                self._removeAttribsRecursively(mnode, self.stripattr)
                if mnode.nodeName == "g":
                    # remove IDs of grouped shapes to prevent duplicates down the line
                    for node in mnode.childNodes:
                        self._removeAttribsRecursively(node, ["id"])
                if not edit:
                    self.mnode_ids[i] = "%s-%i" %(self.occl_id, len(self.mnode_indexes))
                    mlayer_node.childNodes[i].setAttribute("id", self.mnode_ids[i])
                else:
                    self.mnode_ids[i] = mlayer_node.childNodes[i].attributes["id"].value

        return (svg_node, mlayer_node)

    def findByNoteId(self, note_id):
        """Search collection for notes with given ID"""
        query = "'%s':'%s*'" % ( self.ioflds['id'], note_id )
        logging.debug("query %s", query)
        res = mw.col.findNotes(query)
        return res

    def _findAllNotes(self):
        """Get matching nids by ID"""
        old_occl_id = '%s-%s' % (self.uniq_id, self.opref["occl_tp"])
        res = self.findByNoteId(old_occl_id)
        self.nids = {}
        for nid in res:
            note_id = mw.col.getNote(nid)[self.ioflds['id']]
            self.nids[note_id] = nid
        logging.debug('--------------------')
        logging.debug("res %s", res)
        logging.debug("nids %s", self.nids)

    def _deleteAndIdNotes(self, mlayer_node):
        """
        Determine which mask nodes have been deleted or newly created and, depending
        on which, either delete their respective notes or ID them in correspondence
        with the numbering of older nodes
        """
        uniq_id = self.opref['uniq_id']
        mnode_ids = self.mnode_ids
        nids = self.nids

        # look for missing shapes by note_id
        valid_mnode_note_ids = filter (lambda x:x.startswith(uniq_id), mnode_ids.values())
        valid_nid_note_ids = filter (lambda x:x.startswith(uniq_id), nids.keys())
        # filter out notes that have already been deleted manually
        exstg_mnode_note_ids = [x for x in valid_mnode_note_ids if x in valid_nid_note_ids]
        exstg_mnode_note_nrs = sorted([int(i.split('-')[-1]) for i in exstg_mnode_note_ids])
        # determine available nrs available for note numbering
        if not exstg_mnode_note_nrs:
            # only the case if the user deletes all existing shapes
            max_mnode_note_nr = 0
            full_range = None
            available_nrs = None
        else:
            max_mnode_note_nr = int(exstg_mnode_note_nrs[-1])
            full_range = range(1, max_mnode_note_nr+1)
            available_nrs = set(full_range) - set(exstg_mnode_note_nrs)
            available_nrs = sorted(list(available_nrs))

        # compare note_ids as present in note collection with masks on svg
        deleted_note_ids = set(valid_nid_note_ids) - set(valid_mnode_note_ids)
        deleted_note_ids = sorted(list(deleted_note_ids))
        del_count = len(deleted_note_ids)
        # set notes of missing masks on svg to be deleted
        deleted_nids = [nids[x] for x in deleted_note_ids]

        logging.debug('--------------------')
        logging.debug("valid_mnode_note_ids %s", valid_mnode_note_ids)
        logging.debug("exstg_mnode_note_nrs %s", exstg_mnode_note_nrs)
        logging.debug("max_mnode_note_nr %s", max_mnode_note_nr)
        logging.debug("full_range %s", full_range)
        logging.debug("available_nrs %s", available_nrs)
        logging.debug('--------------------')
        logging.debug("valid_nid_note_ids %s", valid_nid_note_ids)
        logging.debug("deleted_note_ids %s", deleted_note_ids)
        logging.debug("deleted_nids %s", deleted_nids)

        # add note_id to missing shapes
        note_nr_max = max_mnode_note_nr
        new_count = 0
        for nr, idx in enumerate(self.mnode_indexes):
            mnode_id = mnode_ids[idx]
            new_mnode_id = None
            mnode = mlayer_node.childNodes[idx]
            if mnode_id not in exstg_mnode_note_ids:
                if available_nrs:
                    # use gap in note_id numbering
                    note_nr = available_nrs.pop(0)
                else:
                    # increment maximum note_id number
                    note_nr_max = note_nr_max +1
                    note_nr = note_nr_max
                new_mnode_id = self.occl_id + '-' + str(note_nr)
                new_count += 1
                nids[new_mnode_id] = None
            else:
                # update occlusion type
                mnode_id_nr = mnode_id.split('-')[-1]
                new_mnode_id = self.occl_id + '-' + mnode_id_nr
                nids[new_mnode_id] = nids.pop(mnode_id)
            if new_mnode_id:
                mnode.setAttribute("id", new_mnode_id)
                self.mnode_ids[idx] = new_mnode_id

            logging.debug("=====================")
            logging.debug("nr %s", nr)
            logging.debug("idx %s", idx)
            logging.debug("mnode_id %s", mnode_id)
            logging.debug("available_nrs %s", available_nrs)
            logging.debug("note_nr_max %s", note_nr_max)
            logging.debug("new_mnode_id %s", new_mnode_id)

        logging.debug('--------------------')
        logging.debug("edited nids %s", nids)
        logging.debug("edited self.mnode_ids %s", self.mnode_ids)

        if del_count or new_count:
            q = "This will <b>delete %i card(s)</b> and \
                 <b>create %i new one(s)</b>.\
                 Please note that this action is irreversible.<br><br>\
                 Would you still like to proceed?" % (del_count, new_count)
            if not ioAskUser(q, title="Please confirm action",
                                    parent=mw.ImgOccEdit, help="editing"):
                return False

        if deleted_nids:
            mw.col.remNotes(deleted_nids)
        return (del_count, new_count)

    def _addImageToCol(self):
        """Rename image based on ID and copy it to the media collection"""
        media_dir = mw.col.media.dir()
        fn = os.path.basename(self.image_path)
        name, ext = os.path.splitext(fn)
        short_name = name[:75] if len(name) > 75 else name
        unique_fn = self.uniq_id + '_' + short_name + ext
        new_path = os.path.join(media_dir, unique_fn)
        shutil.copyfile(self.image_path, new_path)
        return new_path

    def _generateMaskSVGsFor(self, side):
        """Generate a mask for each mask node"""
        masks = [self._createMask(side, node_index) for node_index in self.mnode_indexes]
        return masks

    def _createMask(self, side, mask_node_index):
        """Call occl_tp-specific mask generator"""
        mask_doc = minidom.parseString(self.new_svg)
        svg_node = mask_doc.documentElement
        layer_nodes = self.layerNodesFrom(svg_node)
        mlayer_node = layer_nodes[-1] # treat topmost layer as masks layer
        #This method gets implemented differently by subclasses
        self._createMaskAtLayernode(side, mask_node_index, mlayer_node)
        return svg_node.toxml()

    def _createMaskAtLayernode(self, mask_node_index, mlayer_node):
        raise NotImplementedError

    def _setQuestionAttribs(self, node):
        """Set question node color and class"""
        if (node.nodeType == node.ELEMENT_NODE):
            # set question class
            node.setAttribute("class", "qshape")
            if node.hasAttribute("fill"):
                # set question color
                node.setAttribute("fill", self.qfill)
            map(self._setQuestionAttribs, node.childNodes)

    def _removeAttribsRecursively(self, node, attrs):
        """Remove provided attributes recursively from node and children"""
        if (node.nodeType == node.ELEMENT_NODE):
            for i in attrs:
                if node.hasAttribute(i):
                    node.removeAttribute(i)
            for i in node.childNodes:
                self._removeAttribsRecursively(i, attrs)

    def _saveMask(self, mask, note_id, mtype):
        """Write mask to file in media collection"""
        logging.debug("!saving %s, %s", note_id, mtype)
        # media collection is the working directory:
        mask_path = '%s-%s.svg' % (note_id, mtype)
        mask_file = open(mask_path, 'w')
        mask_file.write(mask)
        mask_file.close()
        return mask_path

    def _saveMaskAndReturnNote(self, omask_path, qmask, amask,
                                img, note_id, nid=None):
        """Write actual note for given qmask and amask"""
        fields = self.fields
        model = self.model
        mflds = self.mflds
        fields[self.ioflds['im']] = img
        if omask_path:
            # Occlusions updated
            qmask_path = self._saveMask(qmask, note_id, "Q")
            amask_path = self._saveMask(amask, note_id, "A")
            fields[self.ioflds['qm']] = fname2img(qmask_path)
            fields[self.ioflds['am']] = fname2img(amask_path)
            fields[self.ioflds['om']] = fname2img(omask_path)
            fields[self.ioflds['id']] = note_id

        self.model['did'] = self.did
        if nid:
            note = mw.col.getNote(nid)
        else:
            note = Note(mw.col, model)

        # add fields to note
        note.tags = self.tags
        for i in mflds:
            fname = i["name"]
            if fname in fields:
                # only update fields that have been modified
                note[fname] = fields[fname]

        if nid:
            note.flush()
            logging.debug("!noteflush %s", note)
        else:
            mw.col.addNote(note)
            logging.debug("!notecreate %s", note)


# Different generator subclasses for different occlusion types:

class IoGenHideAllRevealOne(ImgOccNoteGenerator):
    """Q: All hidden, A: One revealed ('nonoverlapping')"""
    def __init__(self, ed, svg, image_path, opref, tags, fields, did):
        self.occl_tp = "ao"
        ImgOccNoteGenerator.__init__(self, ed, svg, image_path,
                                        opref, tags, fields, did)

    def _createMaskAtLayernode(self, side, mask_node_index, mlayer_node):
        for i in self.mnode_indexes:
            if i == mask_node_index:
                if side == "Q":
                    self._setQuestionAttribs(mlayer_node.childNodes[i])
                if side == "A":
                    mlayer_node.removeChild(mlayer_node.childNodes[i])

class IoGenHideAllRevealAll(ImgOccNoteGenerator):
    """Q: All hidden, A: All revealed"""
    def __init__(self, ed, svg, image_path, opref, tags, fields, did):
        self.occl_tp = "aa"
        ImgOccNoteGenerator.__init__(self, ed, svg, image_path,
                                        opref, tags, fields, did)

    def _createMaskAtLayernode(self, side, mask_node_index, mlayer_node):
        for i in reversed(self.mnode_indexes):
            if side == "Q":
                if i == mask_node_index:
                    self._setQuestionAttribs(mlayer_node.childNodes[i])
            else:
                mlayer_node.removeChild(mlayer_node.childNodes[i])

class IoGenHideOneRevealAll(ImgOccNoteGenerator):
    """Q: One hidden, A: All revealed ('overlapping')"""
    def __init__(self, ed, svg, image_path, opref, tags, fields, did):
        self.occl_tp = "oa"
        ImgOccNoteGenerator.__init__(self, ed, svg, image_path,
                                        opref, tags, fields, did)

    def _createMaskAtLayernode(self, side, mask_node_index, mlayer_node):
        for i in reversed(self.mnode_indexes):
            if i == mask_node_index and side == "Q":
                self._setQuestionAttribs(mlayer_node.childNodes[i])
                mlayer_node.childNodes[i].setAttribute("class", "qshape")
            else:
                mlayer_node.removeChild(mlayer_node.childNodes[i])
