import { getCategories } from '@/lib/category-actions'
import { AppShell } from '@/components/AppShell'
import { SettingsPanel } from '@/components/SettingsPanel'
import { CategoriesEditor } from '@/components/CategoriesEditor'
import { Card, CardContent } from '@/components/ui/card'

export const dynamic = 'force-dynamic'

export default async function SettingsPage() {
    const { categories } = await getCategories()
    return (
        <AppShell active="/settings">
            <Card>
                <CardContent className="space-y-8 pt-6">
                    <SettingsPanel />
                    <CategoriesEditor initial={categories} />
                </CardContent>
            </Card>
        </AppShell>
    )
}
