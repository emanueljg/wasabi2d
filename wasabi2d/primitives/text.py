import unicodedata

import moderngl
import numpy as np

from ..allocators.vertlists import VAO
from ..loaders import fonts
from ..sprites import Colorable, Transformable, TEXTURED_QUADS_PROGRAM, QUAD
from ..atlas import Atlas


class TextVAO(VAO):
    """A VAO for rendering text."""

    def render(self):
        self.prog['tex'].value = 0
        self.tex.use(0)
        super().render()


def text_vao(
        ctx: moderngl.Context,
        shadermgr: 'wasabi2d.layers.ShaderManager') -> VAO:
    """Build a BAO for rendering plain colored objects."""
    return TextVAO(
        mode=moderngl.TRIANGLES,
        ctx=ctx,
        prog=shadermgr.get(**TEXTURED_QUADS_PROGRAM),
        dtype=np.dtype([
            ('in_vert', '2f4'),
            ('in_color', '4f4'),
            ('in_uv', '2f4'),
        ])
    )


class FontAtlas(Atlas):
    """The combination of a font and the texture atlas it uses."""
    def __init__(self, ctx, font_name):
        super().__init__(ctx)
        self.font = fonts.load(font_name, fontsize=48)

    def set_anchor(self, verts, w, h):
        """Set the anchor position to the bottom-left of the glyph."""
        verts -= (w, h, 0)

    def _load(self, name):
        """Load the image for the given name."""
        return self.font.render(name, True, (255, 255, 255))


class Label(Colorable, Transformable):
    """A single-line text block with no additional layout/wrapping."""

    def __init__(
            self,
            text: str,
            font_atlas: FontAtlas,
            layer,
            *,
            align='left',
            fontsize=20,
            pos=(0, 0),
            color=(1, 1, 1, 1)):

        super().__init__()
        self.layer = layer
        self.fontsize = fontsize
        self.font_atlas = font_atlas
        self.pos = pos
        self.color = color
        self.text = text

    def _set_dirty(self):
        self.layer._dirty.add(self)

    @property
    def text(self) -> str:
        """Get the text of this label."""
        return self._text

    @text.setter
    def text(self, text: str):
        """Set the text of this label.

        The string is currently normalised to composed form because this
        is simpler to lay out than a string with combining characters, and
        we may not be very sophisticated at this point.

        """
        text = unicodedata.normalize('NFKC', text)
        self._text = text
        self._layout()

        self._set_dirty()

    def _layout(self):
        """Generate indices, uvs and verts for the text."""
        font = self.font_atlas.font

        # (min_x, max_x, min_y, max_y, horizontal_advance_x)
        metrics = np.array(font.metrics(self._text), dtype='f4')
        cx = np.cumsum(metrics[:, 4]).reshape(-1, 1)
        xpos = metrics[:, 0:2] + cx

        descent = font.get_descent()
        n_chars = len(metrics)

        assert n_chars == len(self._text)
        verts = np.ones((4 * n_chars, 3), dtype='f4')
        uvs = np.zeros((4 * n_chars, 2), dtype='f4')
        indices = np.zeros(len(metrics) * 6, dtype='u4')

        tex = None
        tex_ids = set()
        for idx, char in enumerate(self._text):
            tex, glyph_uvs, glyph_verts = self.font_atlas.get(char)
            tex_ids.add(tex.glo)

            # The kerning seems pretty bad on Pygame fonts...
#            glyph_width = glyph_verts[1, 0] - glyph_verts[0, 0]
#            metrics_width = xpos[idx, 1] - xpos[idx, 0]
#            print(repr(char), glyph_width, metrics_width, metrics[idx, 4])

            x = xpos[idx, 0]
            glyph_slice = slice(idx * 4, idx * 4 + 4)
            verts[glyph_slice] = glyph_verts + (x, -descent, 0)
            uvs[glyph_slice] = glyph_uvs
            indices[6 * idx:6 * idx + 6] = QUAD + 4 * idx

        # Scale coordinates
        resize = np.identity(3, dtype='f4')
        scale = self.fontsize / 48
        resize[0, 0] = scale
        resize[1, 1] = scale

        # TODO: handle use of multiple textures. We will be able to handle
        # this eventually by selecting texture unit within the shader, or by
        # making multiple draw calls
        assert len(tex_ids) == 1, "Label got allocated over multiple textures"
        self.tex = tex
        self._verts = verts @ resize
        self._uvs = uvs
        self._indices = indices

        # TODO: update self.lst, set dirty OR reallocate self.lst for new size

    def _update(self):
        xform = self._scale @ self._rot @ self._xlate

        self.lst.vertbuf['in_vert'] = (self._verts @ xform)[:, :2]
        self.lst.vertbuf['in_color'] = self._color
        self.lst.dirty = True

    def _migrate(self, vao: TextVAO):
        """Migrate the fill into the given VAO."""
        # TODO: dealloc from an existing VAO
        idxs = self._indices
        self.vao = vao
        self.vao.tex = self.tex
        self.lst = vao.alloc(len(self._verts), len(idxs))
        self.lst.indexbuf[:] = idxs
        self.lst.vertbuf['in_uv'] = self._uvs
        self._update()
