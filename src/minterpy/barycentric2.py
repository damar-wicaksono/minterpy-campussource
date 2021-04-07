#!/usr/bin/env python
""" TODO

"""

import numpy as np
from numba import njit
from numba.typed import List

from minterpy.dds import dds_1_dimensional, get_direct_child_idxs
from minterpy.global_settings import ARRAY, TYPED_LIST, FLOAT_DTYPE, TRAFO_DICT

__author__ = "Jannik Michelfeit"
__copyright__ = "Copyright 2021, minterpy"
__credits__ = ["Jannik Michelfeit"]
# __license__ =
# __version__ =
# __maintainer__ =
__email__ = "jannik@michelfe.it"
__status__ = "Development"


@njit(cache=True)
def compute_dds_solutions(generating_points: ARRAY, problem_sizes: TYPED_LIST) -> TYPED_LIST:
    dimensionality = len(problem_sizes)  # TODO rename
    dds_solutions = List()  # use Numba typed list
    for dim_idx in range(dimensionality):
        max_problem_size = problem_sizes[dim_idx][0]
        dds_solution_max = np.eye(max_problem_size, dtype=FLOAT_DTYPE)
        gen_vals = generating_points[dim_idx]  # ATTENTION: different in each dimension!
        # TODO optimise 1D dds for diagonal input <-> output!
        dds_1_dimensional(gen_vals, dds_solution_max)  # O(n^2)
        dds_solutions.append(dds_solution_max)

    return dds_solutions


@njit(cache=True)
def expand_solution(prev_solutions: TRAFO_DICT, dds_solution_max: ARRAY, dim_idx_par: int, split_positions: TYPED_LIST,
                    subtree_sizes: TYPED_LIST, problem_sizes: TYPED_LIST) -> TRAFO_DICT:
    expanded_solutions = dict()  # required Numba numba.typed.Dict
    splits_in_dim = split_positions[dim_idx_par]
    nr_nodes_in_dim = len(splits_in_dim)
    dim_idx_child = dim_idx_par - 1
    # perform "1D" DDS! of the maximal appearing size in the current dimension!
    # NOTE: due to the lexicographical ordering the first node is always the largest
    # TODO precompute and store DDS solutions

    # for all COMBINATIONS of parent nodes (NOTE: different than in usual DDS!)
    for node_idx_par_l in range(nr_nodes_in_dim):
        first_child_idx, last_child_idx = get_direct_child_idxs(dim_idx_par, node_idx_par_l, split_positions,
                                                                subtree_sizes)
        child_idx_range_l = range(first_child_idx, last_child_idx + 1)  # ATTENTION: also include the last node!
        # for all nodes to the right including the selected left node!
        for node_idx_par_r in range(node_idx_par_l, nr_nodes_in_dim):
            first_child_idx_r, last_child_idx_r = get_direct_child_idxs(dim_idx_par, node_idx_par_r,
                                                                        split_positions,
                                                                        subtree_sizes)
            nr_children_r = last_child_idx_r - first_child_idx_r + 1

            # the solution of the parent node combination (= triangular matrix)
            # contains the the required factors for all child solutions
            factors = prev_solutions[node_idx_par_l, node_idx_par_r]

            # ATTENTION: relative and absolute indexing required
            for idx_l_rel, idx_l_abs in enumerate(child_idx_range_l):
                node_size_l = problem_sizes[dim_idx_child][idx_l_abs]
                # iterate over the child nodes of the right parent
                # NOTE: in each iteration on less node needs to be considered
                # (the factor would be 0 due to the lower triangular form)
                for idx_r_rel in range(idx_l_rel, nr_children_r):
                    idx_r_abs = first_child_idx_r + idx_r_rel
                    node_size_r = problem_sizes[dim_idx_child][idx_r_abs]
                    factor = factors[idx_r_rel, idx_l_rel]
                    # the solution for a combination of child nodes consists of
                    # the top left part of the DDS solution with the correct size
                    # multiplied by the factor of the parent
                    expanded_solution = dds_solution_max[:node_size_r, :node_size_l] * factor
                    expanded_solutions[idx_l_abs, idx_r_abs] = expanded_solution
    return expanded_solutions


@njit(cache=True)
def barycentric_dds(generating_points: ARRAY, split_positions: TYPED_LIST,
                    subtree_sizes: TYPED_LIST, problem_sizes: TYPED_LIST) -> TRAFO_DICT:
    """ divided difference scheme for multiple dimensions

    returns:  the fully expanded nested triangular matrix encoded in a dictionary
        = a triangular array piece for every leaf node combination

    modified version using only the regular 1D DDS function
    This is the core algorithm for the computation of the barycentric L2N transformation

    TODO option for stopping in one dimension

    TODO remove


    -> perform the nD DDS for this special case directly "on the leaf level"
    this simplifies to computing a factor for every leaf node match (<-> matrix piece in the transformation)

    NOTE: only use case is calling this with the identity matrix?!
    TODO optimise for this use case

    ATTENTION: what results will be "passed on" is determined by the order of recursion of the dds!
    this depends on the subtree structure (<-> in which dimensions two leaf nodes are "related")
    this makes the simplification of the "leaf node level dds" very hard without completely copying the original dds!

    tl;dr idea description:

    from a global perspective the desired solution (Lagrange coefficients) is the identity matrix
    for each leaf (local perspective) the solution is 1 on the corresponding unisolvent nodes and 0 everywhere else!
    this property enables some simplifications

    from left to right
    FIRST push desired solution (Lagrange) of this node to all siblings to the right
     ("downwards" in the transformation matrix)
    dive each by "leaf" difference Q_H
    solution_right = (solution_right - solution_left) / (val_right - val_left)
    solution_corrected = (solution_expected - correction) / Q_H
    THEN compute solution with 1D DDS

    referencing the parts of the matrix by selecting two leaf nodes:
    node 1 corresponds to the selected input (= Lagrange coefficients) <-> "left to right"
    node 2 corresponds to the selected output (= Newton coefficients) <-> "top to bottom"

    the parts ABOVE the diagonal are all 0 -> no computations required

    for the parts of the matrix ON the diagonal (node 1 = node 2):
    the desired solution (starting value) is the identity matrix I (with the size of this leaf node)
    the previous desired solutions ("to the top") are all 0
    -> the correction of the previous nodes EACH only causes a division
    solution_corrected_0 = I
    solution_corrected = solution_corrected / Q_H
    the value selection is based on the active initial exponents of the leaf nodes

    all parts BELOW the diagonal (node 1 left of node 2 in the tree)
    the size is (size node 2, size node 1)
    the desired solution (starting value) is all 0
    the previous desired solutions ("to the top") are all 0 above the diagonal
    -> these values cause no correction. the desired solutions stay all 0
    solution_corrected = (0 - 0) / Q_H = 0
    NOTE: this corresponds to results not passing "left-right splits in the tree"
    <-> independence of sub-problems to the right (= towards the "bottom" of the matrix)
    the previous desired solutions on the diagonal are equal to the identity I
    -> cause a correction and a division
    solution_corrected = (0 - I) / Q_H =  - I / Q_H
    the previous desired solutions below the diagonal are again all 0, but now each cause a division!
    solution_corrected = solution_corrected / Q_H
    """
    # "expand" nested DDS solution
    # TODO explain top down bottom up

    # starting from the "scalar 1 solution" <-> identity matrix

    dimensionality = len(split_positions)
    dim_idx_par = dimensionality - 1
    dds_solutions = compute_dds_solutions(generating_points, problem_sizes)
    dds_solution_max = dds_solutions[dim_idx_par]

    # IDEA: use a dictionary to represent composite triangular matrices
    # NOTE: the key consists of the node indices of the direct child nodes in each dimension
    # TODO improve performance, lookup
    curr_solutions = {(0, 0): dds_solution_max}

    # traverse through the "tree" (mimicking recursion)
    for dim_idx_par in range(dimensionality - 1, 0, -1):  # starting from the highest dimension O(m)
        prev_solutions = curr_solutions
        dim_idx_child = dim_idx_par - 1
        dds_solution_max = dds_solutions[dim_idx_child]
        curr_solutions = expand_solution(prev_solutions, dds_solution_max, dim_idx_par, split_positions, subtree_sizes,
                                         problem_sizes)

    # return only the result of the last iteration
    return curr_solutions


@njit(cache=True)
def transform_barycentric_dict(coeffs_in: ARRAY, coeffs_out: ARRAY, trafo_dict: TRAFO_DICT,
                               leaf_positions: ARRAY) -> None:
    """ performs a "piecewise" transformation (barycentric)

    TODO
    version using a dictionary encoding the transformation (= a triangular array piece for every leaf node combination)
    NOTE: this format includes a lot of redundancies,
        because the matrix pieces are actually just multiples of each other!

    transform and sum up the respective parts (slices) of the coefficients
    """
    for (leaf_idx_l, leaf_idx_r), matrix_piece, in trafo_dict.items():
        start_pos_in = leaf_positions[leaf_idx_l]
        start_pos_out = leaf_positions[leaf_idx_r]

        # NOTE: the size of the required slices of the coefficient vectors
        # are implicitly encoded in the size of each transformation matrix piece!
        size_out, size_in = matrix_piece.shape

        end_pos_in = start_pos_in + size_in
        slice_in = coeffs_in[start_pos_in:end_pos_in]
        # TODO exploit property that all matrix pieces are also triangular! -> avoid unnecessary computations!
        # TODO build own function using numpy.triu_indices_from?
        coeff_slice_transformed = matrix_piece @ slice_in

        end_pos_out = start_pos_out + size_out
        slice_out = coeffs_out[start_pos_out:end_pos_out]
        slice_out[:] += coeff_slice_transformed  # sum up


@njit(cache=True)
def merge_trafo_dict(trafo_dict, leaf_positions, leaf_sizes) -> ARRAY:
    expected_size = leaf_positions[-1] + leaf_sizes[-1]
    combined_matrix = np.zeros((expected_size, expected_size), dtype=FLOAT_DTYPE)
    for (leaf_idx_l, leaf_idx_r), matrix_piece, in trafo_dict.items():
        start_pos_in = leaf_positions[leaf_idx_l]
        start_pos_out = leaf_positions[leaf_idx_r]

        # NOTE: the size of the required slices of the coefficient vectors
        # are implicitly encoded in the size of each transformation matrix piece!
        size_out, size_in = matrix_piece.shape
        end_pos_in = start_pos_in + size_in
        end_pos_out = start_pos_out + size_out

        window = combined_matrix[start_pos_out:end_pos_out, start_pos_in:end_pos_in]
        window[:] = matrix_piece

    return combined_matrix
