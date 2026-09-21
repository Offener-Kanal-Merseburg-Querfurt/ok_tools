"""
API endpoints for inventory data.

This module defines the viewsets for the inventory models that will be used
by the rental application to access inventory data via REST API.
"""

from django.conf import settings
from django.db.models import Q
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import InventoryItem, Category, Location, Organization
from .serializers import (
    InventoryItemSerializer, CategorySerializer, 
    LocationSerializer, OrganizationSerializer
)


class InventoryItemViewSet(viewsets.ReadOnlyModelViewSet):
    """API endpoint for inventory items."""
    
    serializer_class = InventoryItemSerializer
    
    def get_queryset(self):
        """Get queryset with optional filtering for user access."""
        queryset = InventoryItem.objects.prefetch_related('units')
        
        # Apply filters based on user access if user_id is provided
        user_id = self.request.query_params.get('user_id', None)
        if user_id:
            try:
                from registration.models import OKUser
                user = OKUser.objects.get(id=user_id)
                
                # Staff users (Mitarbeiter) have access to all items
                if user.is_staff:
                    # No filtering needed - staff can access all items
                    pass
                elif hasattr(user, 'profile') and user.profile and user.profile.member:
                    # Member can access state institution + organization
                    state_institution = getattr(settings, 'STATE_MEDIA_INSTITUTION', 'MSA')
                    organization_owner = getattr(settings, 'ORGANIZATION_OWNER', 'OKMQ')
                    # Filter by owner name, ensuring owner is not None
                    queryset = queryset.filter(
                        owner__isnull=False,
                        owner__name__in=[state_institution, organization_owner]
                    )
                else:
                    # Non-member can only access state media institution
                    state_institution = getattr(settings, 'STATE_MEDIA_INSTITUTION', 'MSA')
                    # Filter by owner name, ensuring owner is not None
                    queryset = queryset.filter(
                        owner__isnull=False,
                        owner__name=state_institution
                    )
            except (OKUser.DoesNotExist, ValueError):
                # If user doesn't exist or invalid ID, return empty queryset
                return InventoryItem.objects.none()
        
        # Apply additional filters if provided
        available_for_rent = self.request.query_params.get('available_for_rent', None)
        if available_for_rent is not None:
            available_for_rent = available_for_rent.lower() == 'true'
            queryset = queryset.filter(available_for_rent=available_for_rent)
        
        status_filter = self.request.query_params.get('status', None)
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        
        # Only return items that are in stock
        queryset = queryset.filter(status='in_stock')
        
        return queryset
    
    @action(detail=True, methods=['get'])
    def check_availability(self, request, pk=None):
        """Check availability of an inventory item."""
        try:
            item = self.get_object()
            quantity = int(request.query_params.get('quantity', 1))
            start_date = request.query_params.get('start_date', None)
            end_date = request.query_params.get('end_date', None)
            
            # For now, just check available quantity (without considering reservations)
            available = (item.quantity or 0) - (item.reserved_quantity or 0) - (item.rented_quantity or 0)
            
            if quantity <= available:
                return Response({
                    'available': True,
                    'message': f'Available: {available} items',
                    'available_quantity': available
                })
            else:
                return Response({
                    'available': False,
                    'message': f'Insufficient quantity: requested {quantity}, available {available}',
                    'available_quantity': available
                }, status=status.HTTP_400_BAD_REQUEST)
        except ValueError:
            return Response({
                'available': False,
                'message': 'Invalid quantity parameter'
            }, status=status.HTTP_400_BAD_REQUEST)
        except InventoryItem.DoesNotExist:
            return Response({
                'available': False,
                'message': 'Item not found'
            }, status=status.HTTP_404_NOT_FOUND)
    
    @action(detail=True, methods=['get'])
    def available_quantity(self, request, pk=None):
        """Get available quantity of an inventory item."""
        try:
            item = self.get_object()
            available = (item.quantity or 0) - (item.reserved_quantity or 0) - (item.rented_quantity or 0)
            return Response({'available_quantity': available})
        except InventoryItem.DoesNotExist:
            return Response({'available_quantity': 0}, status=status.HTTP_404_NOT_FOUND)


class CategoryViewSet(viewsets.ReadOnlyModelViewSet):
    """API endpoint for categories."""
    
    queryset = Category.objects.all()
    serializer_class = CategorySerializer


class LocationViewSet(viewsets.ReadOnlyModelViewSet):
    """API endpoint for locations."""
    
    queryset = Location.objects.all()
    serializer_class = LocationSerializer


class OrganizationViewSet(viewsets.ReadOnlyModelViewSet):
    """API endpoint for organizations."""
    
    queryset = Organization.objects.all()
    serializer_class = OrganizationSerializer