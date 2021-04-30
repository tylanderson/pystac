from abc import (ABC, abstractmethod)
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, cast, TYPE_CHECKING

import pystac as ps
from pystac import STACError
from pystac.link import Link
from pystac.stac_io import STAC_IO
from pystac.utils import (is_absolute_href, make_absolute_href)

if TYPE_CHECKING:
    from pystac.catalog import Catalog as Catalog_Type


class STACObjectType(str, Enum):
    def __str__(self) -> str:
        return str(self.value)

    CATALOG = 'CATALOG'
    COLLECTION = 'COLLECTION'
    ITEM = 'ITEM'
    ITEMCOLLECTION = 'ITEMCOLLECTION'


class STACObject(ABC):
    """A STACObject is the base class for any element of STAC that
    has links e.g. (Catalogs, Collections, or Items). A STACObject has
    common functionality, can be converted to and from Python ``dicts`` representing
    JSON, and can be cloned or copied.

    Attributes:
        links (List[Link]): A list of :class:`~pystac.Link` objects representing
            all links associated with this STACObject.
    """
    id: str

    STAC_OBJECT_TYPE: STACObjectType

    def __init__(self, stac_extensions: List[str]) -> None:
        self.links: List[Link] = []
        self.stac_extensions = stac_extensions

    def validate(self) -> List[Any]:
        """Validate this STACObject.

        Returns a list of validation results, which depends on the validation
        implementation. For JSON Schema validation, this will be a list
        of schema URIs that were used during validation.

        Raises:
            STACValidationError
        """
        import pystac.validation
        return pystac.validation.validate(self)  # type:ignore

    def add_link(self, link: Link) -> None:
        """Add a link to this object's set of links.

        Args:
             link (Link): The link to add.
        """
        link.set_owner(cast(STACObject, self))
        self.links.append(link)

    def add_links(self, links: List[Link]) -> None:
        """Add links to this object's set of links.

        Args:
             links (List[Link]): The links to add.
        """

        for link in links:
            self.add_link(link)

    def remove_links(self, rel: str) -> None:
        """Remove links to this object's set of links that match the given ``rel``.

        Args:
             rel (str): The :class:`~pystac.Link` ``rel`` to match on.
        """

        self.links = [link for link in self.links if link.rel != rel]

    def get_single_link(self, rel: str) -> Optional[Link]:
        """Get single link that match the given ``rel``.

        Args:
             rel (str): The :class:`~pystac.Link` ``rel`` to match on.
        """

        return next((link for link in self.links if link.rel == rel), None)

    def get_links(self, rel: Optional[str] = None) -> List[Link]:
        """Gets the :class:`~pystac.Link` instances associated with this object.

        Args:
            rel (str or None): If set, filter links such that only those
                matching this relationship are returned.

        Returns:
            List[:class:`~pystac.Link`]: A list of links that match ``rel`` if set,
                or else all links associated with this object.
        """
        if rel is None:
            return self.links
        else:
            return [link for link in self.links if link.rel == rel]

    def clear_links(self, rel: Optional[str] = None) -> None:
        """Clears all :class:`~pystac.Link` instances associated with this object.

        Args:
            rel (str or None): If set, only clear links that match this relationship.
        """
        if rel is not None:
            self.links = [link for link in self.links if link.rel != rel]
        else:
            self.links = []

    def get_root_link(self) -> Optional[Link]:
        """Get the :class:`~pystac.Link` representing
        the root for this object.

        Returns:
            :class:`~pystac.Link` or None: The root link for this object,
            or ``None`` if no root link is set.
        """
        return self.get_single_link('root')

    @property
    def self_href(self) -> str:
        """Gets the absolute HREF that is represented by the ``rel == 'self'``
        :class:`~pystac.Link`.

        Raises:
            ValueError: If the self_href is not set, this method will throw a ValueError.
                Use get_self_href if there may not be an href set.
        """
        result = self.get_self_href()
        if result is None:
            raise ValueError(f"{self} does not have a self_href set.")
        return result

    def get_self_href(self) -> Optional[str]:
        """Gets the absolute HREF that is represented by the ``rel == 'self'``
        :class:`~pystac.Link`.

        Returns:
            str or None: The absolute HREF of this object, or ``None`` if
            there is no self link defined.

        Note:
            A self link can exist for objects, even if the link is not read or
            written to the JSON-serialized version of the object. Any object
            read from :func:`STACObject.from_file <pystac.STACObject.from_file>` will
            have the HREF the file was read from set as it's self HREF. All self
            links have absolute (as opposed to relative) HREFs.
        """
        self_link = self.get_single_link('self')
        if self_link:
            return cast(str, self_link.target)
        else:
            return None

    def set_self_href(self, href: Optional[str]) -> None:
        """Sets the absolute HREF that is represented by the ``rel == 'self'``
        :class:`~pystac.Link`.

        Args:
            href (str): The absolute HREF of this object. If the given HREF
                is not absolute, it will be transformed to an absolute
                HREF based on the current working directory. If this is None
                the call will clear the self HREF link.
        """
        root_link = self.get_root_link()
        if root_link is not None and root_link.is_resolved():
            cast(ps.Catalog, root_link.target)._resolved_objects.remove(cast(STACObject, self))

        self.remove_links('self')
        if href is not None:
            self.add_link(Link.self_href(href))

        if root_link is not None and root_link.is_resolved():
            cast(ps.Catalog, root_link.target)._resolved_objects.cache(cast(STACObject, self))

    def get_root(self) -> Optional["Catalog_Type"]:
        """Get the :class:`~pystac.Catalog` or :class:`~pystac.Collection` to
        the root for this object. The root is represented by a
        :class:`~pystac.Link` with ``rel == 'root'``.

        Returns:
            Catalog, Collection, or None:
            The root object for this object, or ``None`` if no root link is set.
        """
        root_link = self.get_root_link()
        if root_link:
            if not root_link.is_resolved():
                root_link.resolve_stac_object()
                # Use set_root, so Catalogs can merge ResolvedObjectCache instances.
                self.set_root(cast(ps.Catalog, root_link.target))
            return cast(ps.Catalog, root_link.target)
        else:
            return None

    def set_root(self, root: Optional["Catalog_Type"]) -> None:
        """Sets the root :class:`~pystac.Catalog` or :class:`~pystac.Collection`
        for this object.

        Args:
            root (Catalog, Collection or None): The root
                object to set. Passing in None will clear the root.
        """
        root_link_index = next(iter([i for i, link in enumerate(self.links) if link.rel == 'root']),
                               None)

        # Remove from old root resolution cache
        if root_link_index is not None:
            root_link = self.links[root_link_index]
            if root_link.is_resolved():
                cast(ps.Catalog, root_link.target)._resolved_objects.remove(self)

        if root is None:
            self.remove_links('root')
        else:
            new_root_link = Link.root(root)
            if root_link_index is not None:
                self.links[root_link_index] = new_root_link
                new_root_link.set_owner(self)
            else:
                self.add_link(new_root_link)
            root._resolved_objects.cache(self)

    def get_parent(self) -> Optional["Catalog_Type"]:
        """Get the :class:`~pystac.Catalog` or :class:`~pystac.Collection` to
        the parent for this object. The root is represented by a
        :class:`~pystac.Link` with ``rel == 'parent'``.

        Returns:
            Catalog, Collection, or None:
                The parent object for this object,
                or ``None`` if no root link is set.
        """
        parent_link = self.get_single_link('parent')
        if parent_link:
            return cast(ps.Catalog, parent_link.resolve_stac_object().target)
        else:
            return None

    def set_parent(self, parent: Optional["Catalog_Type"]) -> None:
        """Sets the parent :class:`~pystac.Catalog` or :class:`~pystac.Collection`
        for this object.

        Args:
            parent (Catalog, Collection or None): The parent
                object to set. Passing in None will clear the parent.
        """

        self.remove_links('parent')
        if parent is not None:
            self.add_link(Link.parent(parent))

    def get_stac_objects(self, rel: str) -> Iterable["STACObject"]:
        """Gets the :class:`~pystac.STACObject` instances that are linked to
        by links with their ``rel`` property matching the passed in argument.

        Args:
            rel (str): The relation to match each :class:`~pystac.Link`'s
                ``rel`` property against.

        Returns:
            Iterable[STACObjects]: A possibly empty iterable of STACObjects that are
            connected to this object through links with the given ``rel``.
        """
        links = self.links[:]
        for i in range(0, len(links)):
            link = links[i]
            if link.rel == rel:
                link.resolve_stac_object(root=self.get_root())
                yield cast("STACObject", link.target)

    def save_object(self, include_self_link: bool = True, dest_href: Optional[str] = None) -> None:
        """Saves this STAC Object to it's 'self' HREF.

        Args:
          include_self_link (bool): If this is true, include the 'self' link with this object.
              Otherwise, leave out the self link.
          dest_href (str): Optional HREF to save the file to. If None, the object will be saved
              to the object's self href.

        Raises:
            :class:`~pystac.STACError`: If no self href is set, this error will be raised.

        Note:
            When to include a self link is described in the `Use of Links section of the
            STAC best practices document
            <https://github.com/radiantearth/stac-spec/blob/v0.8.1/best-practices.md#use-of-links>`_
        """
        if dest_href is None:
            self_href = self.get_self_href()
            if self_href is None:
                raise STACError(
                    'Self HREF must be set before saving without an explicit dest_href.')
            dest_href = self_href

        STAC_IO.save_json(dest_href, self.to_dict(include_self_link=include_self_link))

    def full_copy(self,
                  root: Optional["Catalog_Type"] = None,
                  parent: Optional["Catalog_Type"] = None) -> "STACObject":
        """Create a full copy of this STAC object and any stac objects linked to by
        this object.

        Args:
            root (STACObject): Optional root to set as the root of the copied object,
                and any other copies that are contained by this object.
            parent (STACObject): Optional parent to set as the parent of the copy
                of this object.

        Returns:
            STACObject: A full copy of this object, as well as any objects this object
                links to.
        """
        clone = self.clone()

        if root is None and isinstance(clone, ps.Catalog):
            root = clone

        clone.set_root(cast(ps.Catalog, root))
        if parent:
            clone.set_parent(parent)

        link_rels = set(self._object_links())
        for link in clone.links:
            if link.rel in link_rels:
                link.resolve_stac_object()
                target = cast(STACObject, link.target)
                if root is not None and target in root._resolved_objects:
                    cached_target = root._resolved_objects.get(target)
                    assert cached_target is not None
                    target = cached_target
                else:
                    target_parent = None
                    if link.rel in ['child', 'item'] and isinstance(clone, ps.Catalog):
                        target_parent = clone
                    copied_target = target.full_copy(root=root, parent=target_parent)
                    if root is not None:
                        root._resolved_objects.cache(copied_target)
                    target = copied_target
                if link.rel in ['child', 'item']:
                    target.set_root(root)
                    if isinstance(clone, ps.Catalog):
                        target.set_parent(clone)
                link.target = target

        return clone

    # @property
    # def ext(self) -> "ExtensionIndex":
    #     """Access extensions for this STACObject.

    #     Example:
    #         This example shows accessing a Item's EO extension functionality
    #         that gets the band information for an asset::

    #             item = pystac.read_file("eo_item.json")
    #             bands = item.ext.eo.get_asset_bands(item.assets["image"])

    #     Returns:
    #         ExtensionIndex: The object that can be used to access extension information
    #         and functionality.
    #     """
    #     return ExtensionIndex(self)

    def resolve_links(self) -> None:
        """Ensure all STACObjects linked to by this STACObject are
        resolved. This is important for operations such as changing
        HREFs.

        This method mutates the entire catalog tree.
        """
        link_rels = set(self._object_links()) | set(['root', 'parent'])

        for link in self.links:
            if link.rel in link_rels:
                if not link.is_resolved():
                    link.resolve_stac_object(root=self.get_root())

    @abstractmethod
    def _object_links(self) -> List[str]:
        """Inherited classes return a list of link 'rel' types that represent
        STACObjects linked to by this object (not including root, parent or self).
        This can include optional relations (which may not be present).
        """
        pass

    @abstractmethod
    def to_dict(self, include_self_link: bool = True) -> Dict[str, Any]:
        """Generate a dictionary representing the JSON of this serialized object.

        Args:
            include_self_link (bool): If True, the dict will contain a self link
                to this object. If False, the self link will be omitted.

            dict: A serialization of the object that can be written out as JSON.
        """
        pass

    @abstractmethod
    def clone(self) -> "STACObject":
        """Clones this object.

        Cloning an object will make a copy of all properties and links of the object;
        however, it will not make copies of the targets of links (i.e. it is not a
        deep copy). To copy a STACObject fully, with all linked elements also copied,
        use :func:`STACObject.full_copy <pystac.STACObject.full_copy>`.

        Returns:
            STACObject: The clone of this object.
        """
        pass

    @classmethod
    def from_file(cls, href: str) -> "STACObject":
        """Reads a STACObject implementation from a file.

        Args:
            href (str): The HREF to read the object from.

        Returns:
            The specific STACObject implementation class that is represented
            by the JSON read from the file located at HREF.
        """
        if not is_absolute_href(href):
            href = make_absolute_href(href)
        d = STAC_IO.read_json(href)

        o = STAC_IO.stac_object_from_dict(d, href, None)

        # Set the self HREF, if it's not already set to something else.
        if o.get_self_href() is None:
            o.set_self_href(href)

        # If this is a root catalog, set the root to the catalog instance.
        root_link = o.get_root_link()
        if root_link is not None:
            if not root_link.is_resolved():
                if root_link.get_absolute_href() == href:
                    o.set_root(cast(ps.Catalog, o))
        return o

    @classmethod
    @abstractmethod
    def from_dict(cls,
                  d: Dict[str, Any],
                  href: Optional[str] = None,
                  root: Optional["Catalog_Type"] = None,
                  migrate: bool = False) -> "STACObject":
        """Parses this STACObject from the passed in dictionary.

        Args:
            d (dict): The dict to parse.
            href (str): Optional href that is the file location of the object being
                parsed.
            root (Catalog or Collection): Optional root of the catalog for this object.
                If provided, the root's resolved object cache can be used to search for
                previously resolved instances of the STAC object.
            migrate: Use True if this dict represents JSON from an older STAC object,
                so that migrations are run against it.

        Returns:
            STACObject: The STACObject parsed from this dict.
        """
        pass


# class ExtensionIndex:
#     """Defines methods for accessing extension functionality.

#     To access a specific extension, use the __getitem__ on this class with the
#     extension ID::

#         # Access the "bands" property on the eo extension.
#         item.ext['eo'].bands
#     """
#     def __init__(self, stac_object: STACObject) -> None:
#         self.stac_object = stac_object

#     def __getitem__(self, extension_id: str) -> "STACObjectExtension_Type":
#         """Gets the extension object for the given extension.

#         Returns:
#             CatalogExtension or CollectionExtension or ItemExtension: The extension object
#             through which you can access the extension functionality for the extension represented
#             by the extension_id.
#         """
#         # Check to make sure this is a registered extension.
#         if not ps.STAC_EXTENSIONS.is_registered_extension(extension_id):
#             raise ExtensionError("'{}' is not an extension "
#                                  "registered with PySTAC".format(extension_id))

#         if not self.implements(extension_id):
#             raise ExtensionError("{} does not implement the {} extension. "
#                                  "Use the 'ext.enable' method to enable this extension "
#                                  "first.".format(self.stac_object, extension_id))

#         return ps.STAC_EXTENSIONS.extend_object(extension_id, self.stac_object)

#     def __getattr__(self, extension_id: str) -> "STACObjectExtension_Type":
#         """Gets an extension based on a dynamic attribute.

#         This takes the attribute name and passes it to __getitem__.

#         This allows the following two lines to be equivalent::

#             item.ext["label"].label_properties
#             item.ext.label.label_properties
#         """
#         if extension_id.startswith('__') and hasattr(ExtensionIndex, extension_id):
#             return self.__getattribute__(extension_id)
#         return self[extension_id]

#     def enable(self, extension_id: str) -> None:
#         """Enables a stac extension for the given object. If the object already
#         enables the extension, no action is taken. If it does not, the extension ID is
#         added to the object's stac_extension property.

#         Args:
#             extension_id (str): The extension ID representing the extension
#             the object should implement

#         """
#         ps.STAC_EXTENSIONS.enable_extension(extension_id, self.stac_object)

#     def implements(self, extension_id: str) -> bool:
#         """Returns true if the associated object implements the given extension.

#         Args:
#             extension_id (str): The extension ID to check

#         Returns:
#             [bool]: True if the object implements the extensions - i.e. if
#                 the extension ID is in the "stac_extensions" property.
#         """
#         return (self.stac_object.stac_extensions is not None
#                 and extension_id in self.stac_object.stac_extensions)
