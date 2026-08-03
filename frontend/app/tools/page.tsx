import { DemoCta } from '@/components/DemoCta';
import { ModuleGrid } from '@/components/ModuleCard';
import { Container, PageHeader, Section } from '@/components/ui';
import { modules } from '@/content/modules';
import { pageMetadata } from '@/lib/metadata';

export const metadata = pageMetadata('/tools');

export default function ToolsPage() {
  return (
    <>
      <PageHeader
        eyebrow="Tools"
        title="Ten tools, ten specific questions"
        lede="Each module answers one procurement or supply-chain question on documented fictional data, and shows the evidence behind every answer. Open any of them for the business problem, the calculations, what AI does and does not do, and the guided demonstration."
      >
        <DemoCta />
      </PageHeader>

      <Container>
        <Section title="The ten modules">
          <ModuleGrid modules={modules} />
        </Section>
      </Container>
    </>
  );
}
