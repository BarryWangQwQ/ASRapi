# Copyright (c) [2020] [JANVIJAY SINGH]
# Copyright 2020 Huy Le Nguyen (@usimarit)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
This code is originally taken from https://github.com/iamjanvijay/rnnt/blob/master/rnnt/rnnt.py
"""

import tensorflow as tf
try:
    from warprnnt_tensorflow import rnnt_loss as warp_rnnt_loss
    USE_TF=0
except:
    USE_TF=1

from utils.tools import shape_list, nan_to_zero
from tensorflow.python.ops.gen_array_ops import matrix_diag_part_v2

LOG_0 = float("-inf")


def reduce_logsumexp(input_tensor, axis):
    maximum = tf.reduce_max(input_tensor, axis=axis)
    input_tensor = nan_to_zero(input_tensor - maximum)
    return tf.math.log(tf.reduce_sum(tf.exp(input_tensor), axis=axis)) + maximum


def extract_diagonals(log_probs):
    time_steps = tf.shape(log_probs)[1]  # T
    output_steps = tf.shape(log_probs)[2]  # U + 1
    reverse_log_probs = tf.reverse(log_probs, axis=[-1])
    paddings = [[0, 0], [0, 0], [time_steps - 1, 0]]
    padded_reverse_log_probs = tf.pad(reverse_log_probs, paddings,
                                      'CONSTANT', constant_values=LOG_0)
    diagonals = matrix_diag_part_v2(padded_reverse_log_probs, k=(0, time_steps + output_steps - 2),
                                    padding_value=LOG_0)

    return tf.transpose(diagonals, perm=[1, 0, 2])


def transition_probs(one_hot_labels, log_probs):
    """
    :return: blank_probs with shape batch_size x input_max_len x target_max_len
             truth_probs with shape batch_size x input_max_len x (target_max_len-1)
    """
    blank_probs = log_probs[:, :, :, 0]
    truth_probs = tf.reduce_sum(tf.multiply(log_probs[:, :, :-1, :], one_hot_labels), axis=-1)

    return blank_probs, truth_probs


def forward_dp(bp_diags, tp_diags, batch_size, input_max_len, target_max_len):
    """
    :return: forward variable alpha with shape batch_size x input_max_len x target_max_len
    """

    def next_state(x, trans_probs):
        blank_probs = trans_probs[0]
        truth_probs = trans_probs[1]

        x_b = tf.concat([LOG_0 * tf.ones(shape=[batch_size, 1]),
                         x[:, :-1] + blank_probs], axis=1)
        x_t = x + truth_probs

        x = tf.math.reduce_logsumexp(tf.stack([x_b, x_t], axis=0), axis=0)
        return x

    initial_alpha = tf.concat(
        [tf.zeros(shape=[batch_size, 1]), tf.ones(shape=[batch_size, input_max_len - 1]) * LOG_0], axis=1)

    fwd = tf.scan(next_state, (bp_diags[:-1, :, :-1], tp_diags), initializer=initial_alpha)

    alpha = tf.transpose(
        tf.concat([tf.expand_dims(initial_alpha, axis=0), fwd], axis=0), perm=[1, 2, 0])
    alpha = matrix_diag_part_v2(alpha, k=(0, target_max_len - 1), padding_value=LOG_0)
    alpha = tf.transpose(tf.reverse(alpha, axis=[1]), perm=[0, 2, 1])

    return alpha


def backward_dp(bp_diags, tp_diags, batch_size, input_max_len, target_max_len, label_length, logit_length, blank_sl):
    """
        :return: backward variable beta with shape batch_size x input_max_len x target_max_len
    """

    def next_state(x, mask_and_trans_probs):
        mask_s, blank_probs_s, truth_probs = mask_and_trans_probs

        beta_b = tf.concat([x[:, 1:] + blank_probs_s, LOG_0 *
                            tf.ones(shape=[batch_size, 1])], axis=1)
        beta_t = tf.concat([x[:, :-1] + truth_probs, LOG_0 *
                            tf.ones(shape=[batch_size, 1])], axis=1)

        beta_next = reduce_logsumexp(tf.stack([beta_b, beta_t], axis=0), axis=0)
        masked_beta_next = nan_to_zero(beta_next * tf.expand_dims(mask_s, axis=1)) + \
            nan_to_zero(x * tf.expand_dims((1.0 - mask_s), axis=1))
        return masked_beta_next

    # Initial beta for batches.
    initial_beta_mask = tf.one_hot(logit_length - 1, depth=input_max_len + 1)
    initial_beta = tf.expand_dims(blank_sl, axis=1) * initial_beta_mask + \
        nan_to_zero(LOG_0 * (1.0 - initial_beta_mask))

    # Mask for scan iterations.
    mask = tf.sequence_mask(logit_length + label_length - 1, input_max_len + target_max_len - 2,
                            dtype=tf.dtypes.float32)
    mask = tf.transpose(mask, perm=[1, 0])

    bwd = tf.scan(next_state, (mask, bp_diags[:-1, :, :],
                               tp_diags), initializer=initial_beta, reverse=True)

    beta = tf.transpose(tf.concat([bwd, tf.expand_dims(initial_beta, axis=0)], axis=0), perm=[
                        1, 2, 0])[:, :-1, :]
    beta = matrix_diag_part_v2(beta, k=(0, target_max_len - 1), padding_value=LOG_0)
    beta = tf.transpose(tf.reverse(beta, axis=[1]), perm=[0, 2, 1])

    return beta


def compute_rnnt_loss_and_grad_helper(logits, labels, label_length, logit_length):
    batch_size, input_max_len, target_max_len, vocab_size = shape_list(logits)
    # tf.print(shape_list(logits))
    # tf.print(shape_list(labels))
    # tf.print(shape_list(label_length))
    # tf.print(shape_list(logit_length))

    one_hot_labels = tf.one_hot(tf.tile(tf.expand_dims(labels, axis=1),
                                        multiples=[1, input_max_len, 1]), depth=vocab_size)

    log_probs = tf.nn.log_softmax(logits)
    blank_probs, truth_probs = transition_probs(one_hot_labels, log_probs)
    bp_diags = extract_diagonals(blank_probs)
    tp_diags = extract_diagonals(truth_probs)

    label_mask = tf.expand_dims(tf.sequence_mask(
        label_length + 1, maxlen=target_max_len, dtype=tf.float32), axis=1)
    small_label_mask = tf.expand_dims(tf.sequence_mask(
        label_length, maxlen=target_max_len, dtype=tf.float32), axis=1)
    input_mask = tf.expand_dims(tf.sequence_mask(
        logit_length, maxlen=input_max_len, dtype=tf.float32), axis=2)
    small_input_mask = tf.expand_dims(tf.sequence_mask(
        logit_length - 1, maxlen=input_max_len, dtype=tf.float32), axis=2)
    mask = label_mask * input_mask
    grad_blank_mask = (label_mask * small_input_mask)[:, :-1, :]
    grad_truth_mask = (small_label_mask * input_mask)[:, :, :-1]

    alpha = forward_dp(bp_diags, tp_diags, batch_size, input_max_len, target_max_len) * mask

    indices = tf.stack([logit_length - 1, label_length], axis=1)
    blank_sl = tf.gather_nd(blank_probs, indices, batch_dims=1)

    beta = backward_dp(bp_diags, tp_diags, batch_size, input_max_len, target_max_len, label_length, logit_length,
                       blank_sl) * mask
    beta = tf.where(tf.math.is_nan(beta), tf.zeros_like(beta), beta)
    final_state_probs = beta[:, 0, 0]

    # Compute gradients of loss w.r.t. blank log-probabilities.
    grads_blank = -tf.exp((alpha[:, :-1, :] + beta[:, 1:, :] - tf.reshape(final_state_probs,
                                                                          shape=[batch_size, 1, 1]) + blank_probs[:,
                                                                                                                  :-1,
                                                                                                                  :]) * grad_blank_mask) * grad_blank_mask
    grads_blank = tf.concat([grads_blank, tf.zeros(
        shape=(batch_size, 1, target_max_len))], axis=1)
    last_grads_blank = -1 * tf.scatter_nd(
        tf.concat([tf.reshape(tf.range(batch_size, dtype=tf.int32),
                              shape=[batch_size, 1]), indices], axis=1),
        tf.ones(batch_size, dtype=tf.float32), [batch_size, input_max_len, target_max_len])
    grads_blank = grads_blank + last_grads_blank

    # Compute gradients of loss w.r.t. truth log-probabilities.
    grads_truth = -tf.exp((alpha[:, :, :-1] + beta[:, :, 1:] - tf.reshape(final_state_probs, shape=[batch_size, 1,
                                                                                                    1]) + truth_probs) * grad_truth_mask) * grad_truth_mask

    # Compute gradients of loss w.r.t. activations.
    a = tf.tile(tf.reshape(tf.range(target_max_len - 1, dtype=tf.int32), shape=(1, 1, target_max_len - 1, 1)),
                multiples=[batch_size, 1, 1, 1])
    b = tf.reshape(labels - 1, shape=(batch_size, 1, target_max_len - 1, 1))
    c = tf.concat([a, b], axis=3)
    d = tf.tile(c, multiples=(1, input_max_len, 1, 1))
    e = tf.tile(tf.reshape(tf.range(input_max_len, dtype=tf.int32), shape=(1, input_max_len, 1, 1)),
                multiples=(batch_size, 1, target_max_len - 1, 1))
    f = tf.concat([e, d], axis=3)
    g = tf.tile(tf.reshape(tf.range(batch_size, dtype=tf.int32), shape=(batch_size, 1, 1, 1)),
                multiples=[1, input_max_len, target_max_len - 1, 1])
    scatter_idx = tf.concat([g, f], axis=3)
    # TODO - improve the part of code for scatter_idx computation.
    probs = tf.exp(log_probs)
    grads_truth_scatter = tf.scatter_nd(scatter_idx, grads_truth,
                                        [batch_size, input_max_len, target_max_len, vocab_size-1])
    grads = tf.concat(
        [tf.reshape(grads_blank, shape=(batch_size, input_max_len, target_max_len, -1)), grads_truth_scatter], axis=3)
    grads_logits = grads - probs * (tf.reduce_sum(grads, axis=3, keepdims=True))

    loss = -final_state_probs
    return loss, grads_logits


# @tf.function(experimental_relax_shapes=True,input_signature=[tf.TensorSpec([None, None, None, None], dtype=tf.float32),
#                                                              tf.TensorSpec([None, None], dtype=tf.int32),
#                                                              tf.TensorSpec([None], dtype=tf.int32),
#                                                              tf.TensorSpec([None,], dtype=tf.int32)])
def tf_rnnt_loss(logits, labels, label_length, logit_length):
    name = "rnnt_loss"
    with tf.name_scope(name):
        logits = tf.convert_to_tensor(logits,dtype=tf.float32, name="logits")
        labels = tf.convert_to_tensor(labels, dtype=tf.int32,name="labels")
        label_length = tf.convert_to_tensor(label_length, name="label_length")
        logit_length = tf.convert_to_tensor(logit_length, name="logit_length")

        args = [logits, labels, label_length, logit_length]

        @tf.custom_gradient
        def compute_rnnt_loss_and_grad(logits_t, labels_t, label_length_t, logit_length_t):
            """Compute RNN-T loss and gradients."""
            logits_t.set_shape(logits.shape)
            labels_t.set_shape(labels.shape)
            label_length_t.set_shape(label_length.shape)
            logit_length_t.set_shape(logit_length.shape)
            kwargs = dict(logits=logits_t, labels=labels_t,
                          label_length=label_length_t, logit_length=logit_length_t)
            result = compute_rnnt_loss_and_grad_helper(**kwargs)

            def grad(grad_loss):
                grads = [tf.reshape(grad_loss, [-1, 1, 1, 1]) * result[1]]
                grads += [None] * (len(args) - len(grads))
                return grads

            return result[0], grad

        return compute_rnnt_loss_and_grad(*args)

def rnnt_ctc_loss(logits, labels, label_length, logit_length, blank=0):
    logits = tf.reduce_sum(logits, 2)
    _,_,c=shape_list(logits)
    if (c-1)==blank:
        logits=tf.nn.softmax(logits,-1)
        return tf.keras.backend.ctc_batch_cost(labels,logits,tf.expand_dims(logit_length,-1),tf.expand_dims(label_length,-1))
    else:

        return tf.nn.ctc_loss(
        labels=tf.cast(labels, tf.int32),
        logit_length=tf.cast(logit_length, tf.int32),
        logits=tf.cast(logits, tf.float32),
        label_length=tf.cast(label_length, tf.int32),
        logits_time_major=False,
        blank_index=blank
    )
@tf.function
def rnnt_loss(logits, labels, label_length, logit_length, blank=0):
    if not tf.config.list_physical_devices('GPU'):
        logits = tf.nn.log_softmax(logits)
    loss = warp_rnnt_loss(
        acts=tf.cast(logits, tf.float32),
        label_lengths=tf.cast(label_length, tf.int32),
        labels=tf.cast(labels, tf.int32),
        input_lengths=tf.cast(logit_length, tf.int32),
        blank_label=blank
    )
    return loss
