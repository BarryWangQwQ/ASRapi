import numpy as np
import tensorflow as tf


def get_angles(pos, i, d_model):
    angle_rates = 1 / np.power(10000, (2 * (i // 2)) / np.float32(d_model))
    return pos * angle_rates


def positional_encoding(position, d_model):
    angle_rads = get_angles(np.arange(position)[:, np.newaxis],
                            np.arange(d_model)[np.newaxis, :],
                            d_model)

    # apply sin to even indices in the array; 2i
    angle_rads[:, 0::2] = np.sin(angle_rads[:, 0::2])

    # apply cos to odd indices in the array; 2i+1
    angle_rads[:, 1::2] = np.cos(angle_rads[:, 1::2])

    pos_encoding = angle_rads[np.newaxis, ...]

    return tf.cast(pos_encoding, dtype=tf.float32)


def create_padding_mask(seq):
    seq_pad = tf.cast(tf.equal(seq, 0), tf.float32)
    # seq_pad = tf.clip_by_value(seq_pad,0.,1.)

    # add extra dimensions to add the padding
    # to the attention logits.
    return seq_pad[:, tf.newaxis, tf.newaxis, :]  # (batch_size, 1, 1, seq_len)


def create_look_ahead_mask(size):
    mask = 1 - tf.linalg.band_part(tf.ones((size, size)), -1, 0)
    return mask  # (seq_len, seq_len)


def scaled_dot_product_attention(q, k, v, mask):
    """Calculate the attention weights.
    q, k, v must have matching leading dimensions.
    k, v must have matching penultimate dimension, i.e.: seq_len_k = seq_len_v.
    The mask has different shapes depending on its type(padding or look ahead)
    but it must be broadcastable for addition.

    Args:
      q: query shape == (..., seq_len_q, depth)
      k: key shape == (..., seq_len_k, depth)
      v: value shape == (..., seq_len_v, depth_v)
      mask: Float tensor with shape broadcastable
            to (..., seq_len_q, seq_len_k). Defaults to None.

    Returns:
      output, attention_weights
    """

    matmul_qk = tf.matmul(q, k, transpose_b=True)  # (..., seq_len_q, seq_len_k)

    # scale matmul_qk
    dk = tf.cast(tf.shape(k)[-1], tf.float32)
    scaled_attention_logits = matmul_qk / tf.math.sqrt(dk)

    # add the mask to the scaled tensor.
    if mask is not None:
        scaled_attention_logits += (mask * -1e9)

        # softmax is normalized on the last axis (seq_len_k) so that the scores
    # add up to 1.
    attention_weights = tf.nn.softmax(scaled_attention_logits, axis=-1)  # (..., seq_len_q, seq_len_k)

    output = tf.matmul(attention_weights, v)  # (..., seq_len_q, depth_v)

    return output, attention_weights


class MultiHeadAttention(tf.keras.layers.Layer):
    def __init__(self, d_model, num_heads):
        super(MultiHeadAttention, self).__init__()
        self.num_heads = num_heads
        self.d_model = d_model

        assert d_model % self.num_heads == 0

        self.depth = d_model // self.num_heads

        self.wq = tf.keras.layers.Dense(d_model)
        self.wk = tf.keras.layers.Dense(d_model)
        self.wv = tf.keras.layers.Dense(d_model)

        self.dense = tf.keras.layers.Dense(d_model)
        self.mask=None

    def split_heads(self, x, batch_size):
        """Split the last dimension into (num_heads, depth).
        Transpose the result such that the shape is (batch_size, num_heads, seq_len, depth)
        """
        x = tf.reshape(x, (batch_size, -1, self.num_heads, self.depth))
        return tf.transpose(x, perm=[0, 2, 1, 3])

    def call(self, v, k, q):
        batch_size = tf.shape(q)[0]

        q = self.wq(q)  # (batch_size, seq_len, d_model)
        k = self.wk(k)  # (batch_size, seq_len, d_model)
        v = self.wv(v)  # (batch_size, seq_len, d_model)

        q = self.split_heads(q, batch_size)  # (batch_size, num_heads, seq_len_q, depth)
        k = self.split_heads(k, batch_size)  # (batch_size, num_heads, seq_len_k, depth)
        v = self.split_heads(v, batch_size)  # (batch_size, num_heads, seq_len_v, depth)

        # scaled_attention.shape == (batch_size, num_heads, seq_len_q, depth)
        # attention_weights.shape == (batch_size, num_heads, seq_len_q, seq_len_k)
        scaled_attention, attention_weights = scaled_dot_product_attention(
            q, k, v,self.mask)

        scaled_attention = tf.transpose(scaled_attention,
                                        perm=[0, 2, 1, 3])  # (batch_size, seq_len_q, num_heads, depth)

        concat_attention = tf.reshape(scaled_attention,
                                      (batch_size, -1, self.d_model))  # (batch_size, seq_len_q, d_model)

        output = self.dense(concat_attention)  # (batch_size, seq_len_q, d_model)

        return output, attention_weights


def point_wise_feed_forward_network(d_model, dff):
    return tf.keras.Sequential([
        tf.keras.layers.Dense(dff, activation='relu'),  # (batch_size, seq_len, dff)
        tf.keras.layers.Dense(d_model)  # (batch_size, seq_len, d_model)
    ])


class EncoderLayer(tf.keras.layers.Layer):
    def __init__(self, d_model, num_heads, dff, rate=0.1):
        super(EncoderLayer, self).__init__()

        self.mha = MultiHeadAttention(d_model, num_heads)
        self.ffn = point_wise_feed_forward_network(d_model, dff)

        self.layernorm1 = tf.keras.layers.LayerNormalization(epsilon=1e-6)
        self.layernorm2 = tf.keras.layers.LayerNormalization(epsilon=1e-6)

        self.dropout1 = tf.keras.layers.Dropout(rate)
        self.dropout2 = tf.keras.layers.Dropout(rate)

        self.mask=None
    def call(self, x, training=False):
        self.mha.mask=self.mask
        attn_output, _ = self.mha(x, x, x)  # (batch_size, input_seq_len, d_model)
        attn_output = self.dropout1(attn_output, training=training)
        out1 = self.layernorm1(x + attn_output)  # (batch_size, input_seq_len, d_model)

        ffn_output = self.ffn(out1)  # (batch_size, input_seq_len, d_model)
        ffn_output = self.dropout2(ffn_output, training=training)
        out2 = self.layernorm2(out1 + ffn_output)  # (batch_size, input_seq_len, d_model)

        return out2


class DecoderLayer(tf.keras.layers.Layer):
    def __init__(self, d_model, num_heads, dff, rate=0.1):
        super(DecoderLayer, self).__init__()

        self.mha1 = MultiHeadAttention(d_model, num_heads)
        self.mha2 = MultiHeadAttention(d_model, num_heads)

        self.ffn = point_wise_feed_forward_network(d_model, dff)

        self.layernorm1 = tf.keras.layers.LayerNormalization(epsilon=1e-6)
        self.layernorm2 = tf.keras.layers.LayerNormalization(epsilon=1e-6)
        self.layernorm3 = tf.keras.layers.LayerNormalization(epsilon=1e-6)

        self.dropout1 = tf.keras.layers.Dropout(rate)
        self.dropout2 = tf.keras.layers.Dropout(rate)
        self.dropout3 = tf.keras.layers.Dropout(rate)
        self.look_ahead_mask=None
        self.padding_mask=None
    def call(self, x, enc_output, training=False ):
        # enc_output.shape == (batch_size, input_seq_len, d_model)
        self.mha1.mask=self.look_ahead_mask
        self.mha2.mask=self.padding_mask
        attn1, attn_weights_block1 = self.mha1(x, x, x)  # (batch_size, target_seq_len, d_model)
        attn1 = self.dropout1(attn1, training=training)
        out1 = self.layernorm1(attn1 + x)

        attn2, attn_weights_block2 = self.mha2(
            enc_output, enc_output, out1)  # (batch_size, target_seq_len, d_model)
        attn2 = self.dropout2(attn2, training=training)
        out2 = self.layernorm2(attn2 + out1)  # (batch_size, target_seq_len, d_model)

        ffn_output = self.ffn(out2)  # (batch_size, target_seq_len, d_model)
        ffn_output = self.dropout3(ffn_output, training=training)
        out3 = self.layernorm3(ffn_output + out2)  # (batch_size, target_seq_len, d_model)

        return out3, attn_weights_block1, attn_weights_block2


class Encoder(tf.keras.layers.Layer):
    def __init__(self, num_layers, d_model,embedding_dim, num_heads, dff, input_vocab_size,
                 maximum_position_encoding, rate=0.1):
        super(Encoder, self).__init__()

        self.d_model = d_model
        self.num_layers = num_layers
        self.input_embedding_projecter = tf.keras.layers.Dense(d_model, activation='elu')
        self.embedding = tf.keras.layers.Embedding(input_vocab_size, embedding_dim)
        self.pos_encoding = positional_encoding(maximum_position_encoding,
                                                embedding_dim)

        self.enc_layers = [EncoderLayer(d_model, num_heads, dff, rate)
                           for _ in range(num_layers)]
        self.Cnn_layers = [tf.keras.layers.Conv1D(d_model, 3, padding='causal', activation='relu') for _ in
                           range(num_layers)]
        self.dropout = tf.keras.layers.Dropout(rate)
        self.mask=None

    # @tf.function(experimental_relax_shapes=True)
    def call(self, x, training=False):
        seq_len = tf.shape(x)[1]

        # 将嵌入和位置编码相加。
        x = self.embedding(x)  # (batch_size, input_seq_len, d_model)
        x *= tf.math.sqrt(tf.cast(self.d_model, tf.float32))
        x += self.pos_encoding[:, :seq_len, :]

        x = self.dropout(x, training=training)
        x=self.input_embedding_projecter(x)
        for i in range(self.num_layers):
            plus = x
            self.enc_layers[i].mask=self.mask
            x = self.enc_layers[i](x, training)
            x = self.Cnn_layers[i](x)
            x += plus
        return x  # (batch_size, input_seq_len, d_model)


class Decoder(tf.keras.layers.Layer):
    def __init__(self, num_layers, d_model,embedding_dim, num_heads, dff, target_vocab_size,
                 maximum_position_encoding, rate=0.1):
        super(Decoder, self).__init__()

        self.d_model = d_model
        self.num_layers = num_layers

        self.embedding = tf.keras.layers.Embedding(target_vocab_size, embedding_dim)
        self.pos_encoding = positional_encoding(maximum_position_encoding,embedding_dim)
        self.input_embedding_projecter = tf.keras.layers.Dense(d_model, activation='elu')
        self.dec_layers = [DecoderLayer(d_model, num_heads, dff, rate)
                           for _ in range(num_layers)]
        self.Cnn_layers = [tf.keras.layers.Conv1D(d_model, 3, padding='causal', activation='relu') for _ in
                           range(num_layers)]
        self.dropout = tf.keras.layers.Dropout(rate)
        self.ffn = point_wise_feed_forward_network(d_model, dff)
        self.look_ahead_mask=None
        self.padding_mask=None
    # @tf.function(experimental_relax_shapes=True)
    def call(self, x, enc_output, training=False,
             ):
        seq_len = tf.shape(x)[1]
        # attention_weights = {}

        x = self.embedding(x)  # (batch_size, target_seq_len, d_model)
        x *= tf.math.sqrt(tf.cast(self.d_model, tf.float32))
        x += self.pos_encoding[:, :seq_len, :]

        x = self.dropout(x, training=training)
        x= self.input_embedding_projecter(x)
        for i in range(self.num_layers):
            plus = x
            self.dec_layers[i].look_ahead_mask=self.look_ahead_mask
            self.dec_layers[i].padding_mask=self.padding_mask
            x, block1, block2 = self.dec_layers[i](x, enc_output, training)
            x = self.Cnn_layers[i](x)
            x += plus
            # attention_weights['decoder_layer{}_block1'.format(i + 1)] = block1
            # attention_weights['decoder_layer{}_block2'.format(i + 1)] = block2

        # x.shape == (batch_size, target_seq_len, d_model)
        x = self.ffn(x)
        return x  # attention_weights


def create_masks(inp, tar):
    # 编码器填充遮挡
    enc_padding_mask = create_padding_mask(inp)

    # 在解码器的第二个注意力模块使用。
    # 该填充遮挡用于遮挡编码器的输出。
    dec_padding_mask = create_padding_mask(inp)

    # 在解码器的第一个注意力模块使用。
    # 用于填充（pad）和遮挡（mask）解码器获取到的输入的后续标记（future tokens）。
    look_ahead_mask = create_look_ahead_mask(tf.shape(tar)[1])
    dec_target_padding_mask = create_padding_mask(tar)
    combined_mask = tf.maximum(dec_target_padding_mask, look_ahead_mask)

    return enc_padding_mask, combined_mask, dec_padding_mask


class Transformer(tf.keras.Model):
    def __init__(self, num_layers, d_model, enc_embedding_dim,dec_embedding_dim,num_heads, dff, input_vocab_size,
                 target_vocab_size, pe_input, pe_target, rate=0.1, one2one=False, include_decoder=True, **kwargs):
        super(Transformer, self).__init__()

        self.encoder = Encoder(num_layers, d_model, enc_embedding_dim, num_heads, dff,
                               input_vocab_size, pe_input, rate)

        self.to_bert_embedding_projecter=tf.keras.layers.Dense(768)
        self.to_hidden_state=tf.keras.layers.Dense(d_model)
        if not (one2one and not include_decoder):
            if one2one:
                self.decoder = Decoder(num_layers - 1, d_model, dec_embedding_dim, num_heads, dff,
                                       input_vocab_size, pe_target, rate)
            else:
                self.decoder = Decoder(num_layers - 1, d_model, dec_embedding_dim,num_heads, dff,
                                   target_vocab_size, pe_target, rate)
            self.dec_layers = [DecoderLayer(d_model, num_heads, dff, rate)
                               for _ in range(max(num_layers - 1, 1))]
        else:
            self.map_encoders = [EncoderLayer(d_model, num_heads, dff, rate) for _ in range(max(num_layers - 1, 1))]
        self.final_layer = tf.keras.layers.TimeDistributed(tf.keras.layers.Dense(target_vocab_size))
        self.one2one = one2one
        self.include_decoder = include_decoder
        self.start_id=1
        self.end_id=2
        self.enc_mask=None
        self.look_ahead_mask = None
        self.padding_mask = None
    def _build(self):
        x = tf.ones([1,64],tf.int32)
        y = tf.ones([1,64],tf.int32)

        if not (self.one2one and not self.include_decoder):

            self(x, y)
        else:

            self(x)

    def decoder_part(self, enc_output,tar=None, training=False):
        if not (self.one2one and not self.include_decoder):
            dec_output = self.decoder(
                tar, enc_output, training)
            bert_out=self.to_bert_embedding_projecter(dec_output)
            x = self.to_hidden_state(bert_out)
            for layer in self.dec_layers:
                layer.look_ahead_mask=self.decoder.look_ahead_mask
                layer.padding_mask=self.decoder.padding_mask
                x, _, _ = layer(x, enc_output, training)
            x += dec_output
            final_output = self.final_layer(x)  # (batch_size, tar_seq_len, target_vocab_size)
            return final_output, bert_out
        else:
            # x = enc_output
            bert_out= self.to_bert_embedding_projecter( enc_output)
            x=self.to_hidden_state(bert_out)
            for layer in self.map_encoders:
                layer.mask=self.encoder.mask
                x = layer(x, training)

            final_output = self.final_layer(x)

            return final_output,bert_out


    def set_masks(self, enc_padding_mask,look_ahead_mask,dec_padding_mask):
        self.encoder.mask = enc_padding_mask
        if not (self.one2one and not self.include_decoder):
            self.decoder.look_ahead_mask = look_ahead_mask
            self.decoder.padding_mask = dec_padding_mask

    def call(self,inp, tar=None,training=False):
        if not (self.one2one and not self.include_decoder):
            if tar is None:#for convert to pb
                tar=inp
            enc_padding_mask,look_ahead_mask,dec_padding_mask=create_masks(inp, tar)
            self.set_masks(enc_padding_mask, look_ahead_mask, dec_padding_mask)
        else:
            enc_padding_mask = create_padding_mask(inp)
            self.encoder.mask = enc_padding_mask
        enc_output = self.encoder(inp,training=training)  # (batch_size, inp_seq_len, d_model)
        return self.decoder_part(enc_output, tar,training=training)


    @tf.function(experimental_relax_shapes=True,input_signature=[
            tf.TensorSpec([None,None], dtype=tf.int32),
        ])
    def inference(self, inputs):
        if self.one2one:

            out,_=self.call(inputs,inputs)
            out=tf.argmax(out,-1,tf.int32)
            return out
        else:
            enc_padding_mask = create_padding_mask(inputs)
            batch=tf.shape(inputs)[0]
            decoded = tf.cast(tf.ones([batch,1])*self.start_id,tf.int32)
            b_i = 0
            B = tf.shape(inputs)[1] + 1
            self.set_masks(enc_padding_mask, None, None)
            enc_output = self.encoder(inputs, False)
            stop_flag=tf.zeros([batch],tf.float32)
            def _cond(b_i, B,stop_flag, decoded):
                return tf.less(b_i, B)

            def _body(b_i, B,stop_flag, decoded):
                enc_padding_mask, look_ahead_mask, dec_padding_mask = create_masks(inputs, decoded)
                self.set_masks(enc_padding_mask, look_ahead_mask,dec_padding_mask)
                yseq, _ = self.decoder_part(enc_output, decoded)
                yseq = tf.argmax(yseq[:, -1], -1, tf.int32)

                stop_flag+=tf.cast(tf.equal(yseq, self.end_id), 1.)

                hyps = tf.cond(
                    tf.reduce_all(tf.cast(stop_flag,tf.bool)),
                    true_fn=lambda: B,
                    false_fn=lambda: b_i + 1,
                )

                decoded = tf.concat([decoded, tf.expand_dims(yseq,-1)], axis=1)

                return hyps, B,stop_flag, decoded

            _, _,stop_flag, decoded = tf.while_loop(
                _cond,
                _body,
                loop_vars=(b_i, B,stop_flag, decoded),
                shape_invariants=(
                    tf.TensorShape([]),
                    tf.TensorShape([]),
                    tf.TensorShape([None]),
                    tf.TensorShape([None,None])
                )
            )

            return decoded




