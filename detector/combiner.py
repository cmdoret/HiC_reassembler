import numpy as np
import pandas as pd
import pysam as ps

import detector.bam_functions as bm
from sv_class.sv_class import SVs

from os.path import join


np.seterr(divide="ignore", invalid="ignore")


class Combiner(object):
    """
    After all the coords has been detected, we must find which breakpoints form 
    an SV when we combine the two of its (or the three of its for a translocation).
    """

    def __init__(
        self, binsize: int, file_scrambled: str, bamfile: str, tmpdir: str = "./tmpdir",
    ):

        self.binsize = binsize
        self.scrambled = np.load(file_scrambled)
        self.bamfile = bamfile

        self.INV_info = pd.read_csv(join(tmpdir, "INV_detected_info.tsv"), sep="\t")
        self.INS_info = pd.read_csv(join(tmpdir, "INS_detected_info.tsv"), sep="\t")
        self.DEL_info = pd.read_csv(join(tmpdir, "DEL_detected_info.tsv"), sep="\t")

        self.tmpdir = tmpdir

        self.col_bam = 0  # Column where there are coords detected before as SV
        self.col_sgns = 1  # Column where there are BAM coords

    def combine(self):

        # All infos for sv_class
        self.sv_name = list()
        self.sv_type = list()

        self.coordsBP1 = list()
        self.coordsBP2 = list()
        self.coordsBP3 = list()

        self.sgnsBP1 = (
            list()
        )  #  WE DON'T IMPLEMENT HOW TO FIND SGNS SO WE WILL NOT UPDATE THE LIST
        self.sgnsBP2 = list()
        self.sgnsBP3 = list()

        self.size = list()

        # Add_element to the list for each sv

        self.add_INVs()
        self.add_TRA_DEL_INS()

        self.info_sv = SVs(
            np.array(self.sv_name),
            np.array(self.sv_type),
            np.array(self.coordsBP1),
            np.array(self.coordsBP2),
            np.array(self.coordsBP3),
            np.array(self.size),
        )  #  Without the signs because the detection of signs is not implemented yet

        return self.info_sv

    def find_mate(self, coord, allcoords, chrom="Sc_chr04"):

        bam = ps.AlignmentFile(self.bamfile, "rb")

        win = 4
        start = coord - win
        end = coord + win

        ind_coord = 1
        ind_sgn = 2

        coords_reads = list()
        sgns_reads = list()

        for read in bam.fetch(chrom, start, end):

            try:
                read_info = read.get_tag("SA").split(",")
                coords_reads.append(int(read_info[ind_coord]))  # str to int

            except:
                pass

        if len(coords_reads) == 0:
            return -1  #  No mate in this case

        thresold_dis = 5

        mate_found = False
        index_candidate = 0

        while (not mate_found) and (
            index_candidate < len(allcoords.iloc[:, self.col_bam])
        ):

            dis_to_coords = abs(
                allcoords.iloc[index_candidate, self.col_bam] - coords_reads
            )

            if np.min(dis_to_coords) < thresold_dis:

                mate_found = True

                return index_candidate

            index_candidate += 1

        return -1

    def find_all_mates(self, allcoords):
        # Search for each coord detected a mate.
        all_mates = list()
        for index_bp in allcoords.index:

            coord_bam = allcoords.iloc[index_bp, self.col_bam]
            index_other_bp = self.find_mate(coord_bam, allcoords)

            if (
                index_other_bp != -1
            ):  #  When find_mate returns -1, it is that there is no mate found.
                all_mates.append([index_bp, index_other_bp])

        if len(all_mates) > 0:

            all_mates = np.array(all_mates)
            all_mates = np.sort(all_mates, axis=1)

            mates_indexes = np.unique(all_mates, axis=0)
        else:
            mates_indexes = np.array(list())

        return mates_indexes

    def add_INVs(self):

        self.INV_mates_indexes = self.find_all_mates(self.INV_info)

        count_inv = 1
        for indexbp1, indexbp2 in self.INV_mates_indexes:

            self.sv_name.append("INV" + str(count_inv))
            self.sv_type.append("INV")

            self.coordsBP1.append(self.INV_info.iloc[indexbp1, self.col_bam])
            self.coordsBP2.append(self.INV_info.iloc[indexbp2, self.col_bam])
            self.coordsBP3.append(-1)  # No third BP for INV

            ### ADD SOMETHING FOR SIGNS AFTER ###

            self.size.append(
                abs(
                    self.INV_info.iloc[indexbp1, self.col_bam]
                    - self.INV_info.iloc[indexbp2, self.col_bam]
                )
            )

            count_inv += 1

    def find_TRA(self):
        """
        Allows to detect if the insertion is linked to a translocation (so if there is a deletion associated). 
        """

        self.DEL_mates_indexes = self.find_all_mates(
            self.DEL_info
        )  # self because we will re-use this value after

        self.is_TRA = list()

        for DEL_mates in self.DEL_mates_indexes:

            other_index_test_1 = self.find_mate(
                self.DEL_info.iloc[DEL_mates[0], self.col_bam], self.INS_info
            )
            other_index_test_2 = self.find_mate(
                self.DEL_info.iloc[DEL_mates[1], self.col_bam], self.INS_info
            )

            if (other_index_test_1 != -1) | (other_index_test_2 != -1):

                self.is_TRA.append(
                    max(np.max(other_index_test_1), np.max(other_index_test_2))
                )  # Max because one can be -1, the other the true index.

            else:
                self.is_TRA.append(-1)

    def add_TRA_DEL_INS(self):

        self.find_TRA()

        count_tra = 1
        count_del = 1
        count_ins = 1

        for index_DEL_mates in range(0, self.DEL_mates_indexes.shape[0]):

            DEL_mates = self.DEL_mates_indexes[index_DEL_mates]

            if self.is_TRA[index_DEL_mates] != -1:

                INS_index = self.is_TRA[index_DEL_mates]  # INS index linked to TRA

                self.sv_name.append("TRA" + str(count_tra))

                if (
                    min(
                        self.DEL_info.iloc[DEL_mates[0], self.col_bam],
                        self.DEL_info.iloc[DEL_mates[1], self.col_bam],
                    )
                    >= self.INS_info.iloc[INS_index, self.col_bam]
                ):  # When we delete something to put it somewhere after.
                    self.sv_type.append("TRA_forward")
                else:  # When we delete something to put it somewhere before.
                    #  These translocations are different so we separate them.

                    self.sv_type.append("TRA_back")

                self.coordsBP1.append(self.DEL_info.iloc[DEL_mates[0], self.col_bam])
                self.coordsBP2.append(self.INS_info.iloc[INS_index, self.col_bam])
                self.coordsBP3.append(self.DEL_info.iloc[DEL_mates[1], self.col_bam])

                ### ADD SOMETHING FOR SIGNS AFTER ###

                self.size.append(
                    abs(
                        self.DEL_info.iloc[DEL_mates[0], self.col_bam]
                        - self.DEL_info.iloc[DEL_mates[1], self.col_bam]
                    )
                )

                self.INS_info = self.INS_info.drop(
                    INS_index
                )  # drop in order to have after this loop a
                # dataframe with all INS which are not breakpoints.

                count_tra += 1

            else:

                self.sv_name.append("DEL" + str(count_del))
                self.sv_type.append("DEL")

                self.coordsBP1.append(self.DEL_info.iloc[DEL_mates[0], self.col_bam])
                self.coordsBP2.append(self.DEL_info.iloc[DEL_mates[1], self.col_bam])
                self.coordsBP3.append(-1)  # No third BP for DEL

                ### ADD SOMETHING FOR SIGNS AFTER ###

                self.size.append(
                    abs(
                        self.DEL_info.iloc[DEL_mates[0], self.col_bam]
                        - self.DEL_info.iloc[DEL_mates[1], self.col_bam]
                    )
                )

                count_del += 1

        # We delete the rows of INS associated to TRA. We have atin self.INSinfo
        # only INS not linked to TRA.

        self.INS_info.index = np.arange(
            0, len(self.INS_info.index)
        )  #  To have indexes from 0 to 1 (not the cas before because we drop some rows).

        for INS_index in self.INS_info.index:

            self.sv_name.append("INS" + str(count_ins))
            self.sv_type.append("INS")

            self.coordsBP1.append(self.INS_info.iloc[INS_index, self.col_bam])
            self.coordsBP2.append(-1)  # No second BP for INS
            self.coordsBP3.append(-1)  # No third BP for INS

            ### ADD SOMETHING FOR SIGNS AFTER ###

            self.size.append(0)  # IMPLEMENT SOMETHING WHICH FIND SIZE AFTER

            count_ins += 1

    def save_sv_combined(self):

        final_INV_detected = np.sort(
            np.concatenate(
                (
                    self.info_sv.coordsBP1[self.info_sv.sv_type == "INV"],
                    self.info_sv.coordsBP2[self.info_sv.sv_type == "INV"],
                )
            ).reshape((len(self.info_sv.coordsBP1[self.info_sv.sv_type == "INV"]), 2))
            // self.binsize,
            axis=1,
        )

        final_INS_detected = np.sort(
            self.info_sv.coordsBP1[self.info_sv.sv_type == "INS"] // self.binsize,
            axis=0,
        )

        final_DEL_detected = np.sort(
            np.concatenate(
                (
                    self.info_sv.coordsBP1[self.info_sv.sv_type == "DEL"],
                    self.info_sv.coordsBP2[self.info_sv.sv_type == "DEL"],
                )
            ).reshape((len(self.info_sv.coordsBP1[self.info_sv.sv_type == "DEL"]), 2))
            // self.binsize,
            axis=1,
        )

        final_TRA_detected = np.sort(
            np.concatenate(
                (
                    self.info_sv.coordsBP1[
                        (self.info_sv.sv_type == "TRA_back")
                        | (self.info_sv.sv_type == "TRA_forward")
                    ],
                    self.info_sv.coordsBP2[
                        (self.info_sv.sv_type == "TRA_back")
                        | (self.info_sv.sv_type == "TRA_forward")
                    ],
                    self.info_sv.coordsBP3[
                        (self.info_sv.sv_type == "TRA_back")
                        | (self.info_sv.sv_type == "TRA_forward")
                    ],
                )
            ).reshape(
                (
                    len(
                        self.info_sv.coordsBP1[
                            (self.info_sv.sv_type == "TRA_back")
                            | (self.info_sv.sv_type == "TRA_forward")
                        ]
                    ),
                    3,
                )
            )
            // self.binsize,
            axis=1,
        )

        np.save("data/output/detection/INV_detected.npy", final_INV_detected)
        np.save("data/output/detection/INS_detected.npy", final_INS_detected)
        np.save("data/output/detection/DEL_detected.npy", final_DEL_detected)
        np.save("data/output/detection/TRA_detected.npy", final_TRA_detected)
